"""
Source verifier: checks whether a given URL or DOI looks like a genuine,
traceable publication (paper, conference paper, patent, article) rather than
assessing "truth" of its content -- that's what the claim classifier does.
This checks *provenance*: does this actually exist in a real index, who
published it, can anything about it be confirmed independently.

Deliberately conservative in its language: this can raise confidence or flag
a lack of verifiable signals, but it does NOT accuse a source of being fake.
A source with no DOI and an unfamiliar domain might be completely legitimate
(a company blog, a government report with no DOI) -- we say "unverified",
never "fake", because we have no reliable way to prove fraud, only to
confirm or fail to confirm identity.

Two real signals are used, both via free, keyless public APIs:
  1. CrossRef (https://api.crossref.org) -- the registry academic publishers
     use to register DOIs. If a DOI resolves here with matching metadata,
     that's strong evidence the source is a real, registered publication.
  2. Domain reputation -- a short allow-list of well-known scholarly/
     government/standards domains (arXiv, major publishers, .gov, .edu,
     patent offices). This is a heuristic, not a determination.
"""
from __future__ import annotations

import re
import urllib.parse

import requests

_DOI_RE = re.compile(r"10\.\d{4,9}/[^\s\"'<>]+", re.IGNORECASE)

# Domains with a long track record as legitimate scholarly/government/patent
# sources. Not exhaustive -- absence from this list means "unknown", not
# "untrustworthy". Deliberately NOT maintaining a "predatory" blacklist here:
# that list changes constantly and getting it wrong unfairly smears real
# publishers, whereas an allow-list can only ever be incomplete, not wrong.
_REPUTABLE_DOMAIN_HINTS = (
    "arxiv.org", "doi.org", "crossref.org", "semanticscholar.org",
    "ncbi.nlm.nih.gov", "pubmed.ncbi.nlm.nih.gov", "nature.com", "science.org",
    "ieee.org", "ieeexplore.ieee.org", "acm.org", "dl.acm.org", "springer.com",
    "springeropen.com", "sciencedirect.com", "wiley.com", "tandfonline.com",
    "oup.com", "plos.org", "jstor.org", "uspto.gov", "patentsview.org",
    "worldbank.org", "who.int", "un.org",
)
_REPUTABLE_TLD_HINTS = (".gov", ".edu", ".int")

_USER_AGENT = "Evidentia-SourceVerifier/1.0 (evidence-first research assistant)"


def extract_doi(text: str) -> str | None:
    match = _DOI_RE.search(text)
    if not match:
        return None
    doi = match.group(0).rstrip(".,;)")  # trim trailing punctuation a sentence might carry
    return doi


def _domain_of(url: str) -> str:
    try:
        return urllib.parse.urlparse(url if "://" in url else f"https://{url}").netloc.lower()
    except Exception:
        return ""


def check_domain_reputation(url: str) -> dict:
    domain = _domain_of(url)
    for hint in _REPUTABLE_DOMAIN_HINTS:
        if hint in domain:
            return {"tier": "known_scholarly_or_official", "matched": hint, "domain": domain}
    for tld in _REPUTABLE_TLD_HINTS:
        if domain.endswith(tld):
            return {"tier": "government_or_academic_tld", "matched": tld, "domain": domain}
    return {"tier": "unknown", "matched": None, "domain": domain}


def check_crossref(doi: str) -> dict | None:
    """Looks a DOI up against CrossRef. Returns metadata if found, else None.
    Never raises -- a network hiccup here should degrade to 'unverified', not
    crash the whole check."""
    try:
        resp = requests.get(
            f"https://api.crossref.org/works/{urllib.parse.quote(doi, safe='')}",
            headers={"User-Agent": _USER_AGENT},
            timeout=10,
        )
        if resp.status_code != 200:
            return None
        message = resp.json().get("message", {})
        title_list = message.get("title") or []
        return {
            "title": title_list[0] if title_list else None,
            "publisher": message.get("publisher"),
            "type": message.get("type"),
            "published": (message.get("published") or {}).get("date-parts", [[None]])[0],
            "is_retracted": any(
                (u.get("label") or "").lower() == "retraction" for u in message.get("update-to", [])
            ),
        }
    except Exception:
        return None


def verify_source(source: str) -> dict:
    """source: a URL or a bare DOI. Returns {verdict, recommendation, reasons, metadata}."""
    source = source.strip()
    reasons: list[str] = []
    metadata: dict | None = None

    doi = source if source.lower().startswith("10.") else extract_doi(source)
    if doi:
        crossref_result = check_crossref(doi)
        if crossref_result:
            metadata = {"doi": doi, **crossref_result}
            if crossref_result.get("is_retracted"):
                reasons.append("CrossRef lists this work as retracted.")
                return {
                    "source": source,
                    "verdict": "retracted",
                    "recommendation": "Do not cite as current evidence -- CrossRef's own metadata flags this as retracted. If discussing it historically, say so explicitly.",
                    "reasons": reasons,
                    "metadata": metadata,
                }
            reasons.append(f"DOI {doi} resolves on CrossRef to a registered work" + (f' ("{crossref_result["title"]}")' if crossref_result.get("title") else "") + ".")
            if crossref_result.get("publisher"):
                reasons.append(f"Registered publisher: {crossref_result['publisher']}.")
            domain_check = check_domain_reputation(source) if source.startswith("http") else None
            return {
                "source": source,
                "verdict": "likely_genuine",
                "recommendation": "This resolves to a real, registered publication. Still worth skimming the actual text for relevance and reading it in context -- genuineness isn't the same as accuracy or relevance to your specific claim.",
                "reasons": reasons,
                "metadata": metadata,
            }
        else:
            reasons.append(f"A DOI-shaped string ({doi}) was found but didn't resolve on CrossRef -- it may be malformed, very recent, or from a registry CrossRef doesn't cover (e.g. DataCite).")

    if source.startswith("http") or "." in source:
        domain_check = check_domain_reputation(source)
        if domain_check["tier"] != "unknown":
            reasons.append(f"Domain matches a known scholarly/official pattern ({domain_check['matched']}).")
            return {
                "source": source,
                "verdict": "plausible",
                "recommendation": "No DOI to confirm independently, but the domain matches a known scholarly or official pattern. Reasonable to use with normal editorial judgment -- cross-check specific facts against the source text itself.",
                "reasons": reasons,
                "metadata": {"domain": domain_check["domain"]},
            }
        reasons.append(f"Domain ({domain_check['domain'] or 'unparseable'}) doesn't match any known scholarly/government pattern, and no DOI was found to check independently.")

    return {
        "source": source,
        "verdict": "unverified",
        "recommendation": "Couldn't independently confirm this source. That does not mean it's fake -- many legitimate sources (company sites, government reports, niche publications) have no DOI and aren't on any allow-list. Read it critically, check who's behind it, and prefer corroborating it with a second, more easily verified source before relying on it.",
        "reasons": reasons,
        "metadata": None,
    }
