"""
Autonomous research assistant.

Given a topic/question, this module:
  1. asks the NVIDIA LLM to expand it into a handful of diverse search queries
  2. runs each query against general web search (DuckDuckGo) AND three free,
     keyless academic archives -- arXiv (papers/preprints), CrossRef
     (published papers and conference papers, via their DOI registry), and
     best-effort PatentsView (US patents)
  3. fetches and cleans the resulting pages (arXiv abstracts are used
     directly from its API response rather than re-fetched, since that's
     more reliable than scraping the abstract page)
  4. ingests the cleaned pages straight into the case's corpus, exactly like a
     manually pasted document -- they go through the same chunking, the same
     hybrid retriever, the same SQLite persistence
  5. asks the LLM to draft a short paragraph on the topic, grounded ONLY in
     what was just fetched

This closes the loop between "Evidentia checks what you write" and "Evidentia
can go find you something to write from" -- the draft it produces is meant as
a *starting point*, not a finished answer: dropping it into the editor runs it
back through the normal claim-by-claim verification the rest of the app does.
The classifier itself isn't "trained" on these sources in any machine-learning
sense (no fine-tuning happens here) -- the sources become part of the case's
corpus, which is how a RAG system "learns" more: a bigger, better corpus to
retrieve from and judge claims against.

Runs as a FastAPI BackgroundTask (see app/main.py); progress and results are
written to SQLite as it goes (via app/database.py) so the frontend can poll a
job's status instead of holding a single long-lived HTTP request open.

Swappable web search: `web_search()` below is the one function you'd replace
to use a different provider (Tavily, Serper, Bing, etc.) instead of
DuckDuckGo -- everything else in this module only depends on its return shape.
"""
from __future__ import annotations

import json
import re
import urllib.parse
import uuid
import xml.etree.ElementTree as ET

import requests
from bs4 import BeautifulSoup
from duckduckgo_search import DDGS
from openai import OpenAI

from app import database
from app.chunking import chunk_document
from app.config import settings
from app.retrieval import get_retriever

_USER_AGENT = "Evidentia-ResearchBot/1.0 (evidence-first research assistant)"

_QUERY_EXPANSION_PROMPT = """You are a research planning assistant. Given a topic or question, \
propose a short list of distinct, well-formed WEB SEARCH queries that together would surface \
good primary/authoritative sources covering different angles of the topic (not just rephrasings \
of each other).

Respond with ONLY a JSON object, no markdown fences, no preamble:
{"queries": ["query one", "query two", ...]}

Return at most %d queries.
"""

_DRAFT_PROMPT = """You are a careful research assistant drafting the FIRST DRAFT of a paragraph \
on a topic, using ONLY the evidence excerpts provided below. Rules:
- Only state things the evidence actually supports. If the evidence is thin or conflicting on
  some sub-point, say so plainly or omit it rather than filling the gap from general knowledge.
- Write in neutral, plain prose -- 150 to 250 words, no bullet points, no headers.
- Do not fabricate citations or numbers not present in the evidence.
This draft will be checked sentence-by-sentence against the same evidence afterwards, so it's fine
(expected, even) to be cautious rather than comprehensive.
"""


def _nvidia_client() -> OpenAI:
    return OpenAI(api_key=settings.nvidia_api_key, base_url=settings.nvidia_base_url)


def _parse_json_object(raw_text: str) -> dict | None:
    cleaned = raw_text.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        return None


def expand_queries(topic: str) -> list[str]:
    """Turns a topic into up to `research_max_queries` distinct search queries.
    Falls back to just [topic] if the LLM call or parsing fails."""
    try:
        client = _nvidia_client()
        response = client.chat.completions.create(
            model=settings.nvidia_model,
            max_tokens=250,
            temperature=0.3,
            messages=[
                {"role": "system", "content": _QUERY_EXPANSION_PROMPT % settings.research_max_queries},
                {"role": "user", "content": topic},
            ],
        )
        raw_text = response.choices[0].message.content or ""
        parsed = _parse_json_object(raw_text)
        queries = parsed.get("queries") if parsed else None
        if isinstance(queries, list) and queries:
            return [str(q).strip() for q in queries if str(q).strip()][: settings.research_max_queries]
    except Exception:
        pass
    return [topic]


def web_search(query: str, max_results: int) -> list[dict]:
    """Returns [{title, url, snippet, source_type}, ...]. Swap this out for
    another provider's SDK if you'd rather not depend on DuckDuckGo."""
    try:
        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=max_results))
    except Exception:
        return []
    return [
        {
            "title": r.get("title", "").strip(),
            "url": r.get("href", ""),
            "snippet": r.get("body", ""),
            "source_type": "web",
        }
        for r in results
        if r.get("href")
    ]


_ARXIV_NS = {"atom": "http://www.w3.org/2005/Atom"}


def search_arxiv(query: str, max_results: int) -> list[dict]:
    """arXiv's public API -- free, no key, no rate-limit auth required for
    light use. Returns results with the abstract already attached as
    `direct_text`, since that's more reliable than re-scraping the abstract
    page, and arXiv abstracts alone are often substantial enough to use as
    evidence outright."""
    try:
        params = {
            "search_query": f"all:{query}",
            "start": 0,
            "max_results": max_results,
        }
        resp = requests.get(
            "http://export.arxiv.org/api/query",
            params=params,
            headers={"User-Agent": _USER_AGENT},
            timeout=settings.research_fetch_timeout,
        )
        resp.raise_for_status()
        root = ET.fromstring(resp.text)
    except Exception:
        return []

    results = []
    for entry in root.findall("atom:entry", _ARXIV_NS):
        title_el = entry.find("atom:title", _ARXIV_NS)
        summary_el = entry.find("atom:summary", _ARXIV_NS)
        id_el = entry.find("atom:id", _ARXIV_NS)
        if title_el is None or summary_el is None or id_el is None:
            continue
        title = re.sub(r"\s+", " ", title_el.text or "").strip()
        abstract = re.sub(r"\s+", " ", summary_el.text or "").strip()
        url = (id_el.text or "").strip()
        if not title or not abstract or not url:
            continue
        results.append(
            {
                "title": title,
                "url": url,
                "snippet": abstract[:300],
                "source_type": "arxiv",
                "direct_text": abstract,
            }
        )
    return results


def search_crossref(query: str, max_results: int) -> list[dict]:
    """CrossRef's public works API -- free, no key. Covers journal articles
    and a large share of conference papers (anything with a registered DOI).
    Setting `crossref_mailto` in config gets you into CrossRef's faster
    "polite pool"; it's optional."""
    try:
        params = {"query": query, "rows": max_results}
        if settings.crossref_mailto:
            params["mailto"] = settings.crossref_mailto
        resp = requests.get(
            "https://api.crossref.org/works",
            params=params,
            headers={"User-Agent": _USER_AGENT},
            timeout=settings.research_fetch_timeout,
        )
        resp.raise_for_status()
        items = resp.json().get("message", {}).get("items", [])
    except Exception:
        return []

    results = []
    for item in items:
        title_list = item.get("title") or []
        title = title_list[0] if title_list else None
        url = item.get("URL")
        if not title or not url:
            continue
        venue = (item.get("container-title") or [None])[0]
        publisher = item.get("publisher")
        snippet = " / ".join(p for p in (venue, publisher) if p)
        results.append({"title": title, "url": url, "snippet": snippet, "source_type": "crossref"})
    return results


def search_patents(query: str, max_results: int) -> list[dict]:
    """Best-effort US patent search via PatentsView. This API's access model
    has shifted over time (it has moved between fully keyless and requiring
    free registration), so this is deliberately defensive: any failure at
    all -- wrong endpoint, auth required, format changed -- just returns an
    empty list rather than breaking the research run. If you have a
    PatentsView API key, set PATENTSVIEW_API_KEY in .env to use it."""
    try:
        query_json = json.dumps({"_text_any": {"patent_title": query}})
        fields_json = json.dumps(["patent_id", "patent_title", "patent_date", "patent_abstract"])
        url = (
            "https://search.patentsview.org/api/v1/patent/"
            f"?q={urllib.parse.quote(query_json)}&f={urllib.parse.quote(fields_json)}"
        )
        headers = {"User-Agent": _USER_AGENT}
        if settings.patentsview_api_key:
            headers["X-Api-Key"] = settings.patentsview_api_key
        resp = requests.get(url, headers=headers, timeout=settings.research_fetch_timeout)
        if resp.status_code != 200:
            return []
        patents = resp.json().get("patents") or []
    except Exception:
        return []

    results = []
    for p in patents[:max_results]:
        patent_id = p.get("patent_id")
        title = p.get("patent_title")
        abstract = p.get("patent_abstract") or ""
        if not patent_id or not title:
            continue
        results.append(
            {
                "title": title,
                "url": f"https://patents.google.com/patent/US{patent_id}",
                "snippet": abstract[:300],
                "source_type": "patent",
                "direct_text": abstract if len(abstract) >= 200 else None,
            }
        )
    return results


def academic_search(query: str, max_results_per_source: int) -> list[dict]:
    """Runs arXiv + CrossRef + PatentsView for one query and merges results.
    Each source is independently defensive (see above), so one archive being
    down or changed never blocks the others."""
    results: list[dict] = []
    results.extend(search_arxiv(query, max_results_per_source))
    results.extend(search_crossref(query, max_results_per_source))
    results.extend(search_patents(query, max_results_per_source))
    return results


def fetch_readable_text(url: str) -> tuple[str | None, str | None]:
    """Fetches a URL and extracts readable body text (paragraph tags, with
    obvious boilerplate stripped). Returns (title, text) or (None, None) on
    failure / too-thin content."""
    try:
        resp = requests.get(
            url, timeout=settings.research_fetch_timeout, headers={"User-Agent": _USER_AGENT}
        )
        resp.raise_for_status()
    except Exception:
        return None, None

    content_type = resp.headers.get("content-type", "")
    if "html" not in content_type and not resp.text.lstrip().startswith("<"):
        return None, None

    soup = BeautifulSoup(resp.text, "html.parser")
    for tag in soup(["script", "style", "nav", "footer", "header", "form", "noscript", "svg"]):
        tag.decompose()

    title = None
    if soup.title and soup.title.string:
        title = re.sub(r"\s+", " ", soup.title.string).strip()

    paragraphs = [re.sub(r"\s+", " ", p.get_text(" ", strip=True)) for p in soup.find_all("p")]
    paragraphs = [p for p in paragraphs if len(p) > 40]  # drop nav crumbs / captions / boilerplate
    text = "\n".join(paragraphs)[: settings.research_max_chars_per_source]

    if len(text) < 200:  # too thin to be useful evidence
        return None, None
    return title, text


def draft_from_evidence(topic: str, sources: list[dict]) -> str:
    """sources: [{title, text}, ...] (already-ingested pages). Returns a short
    grounded draft paragraph, or a fallback message if drafting fails."""
    if not sources:
        return "No usable sources were found to draft from."

    evidence_block = "\n\n".join(f"[{i}] ({s['title']}) {s['text'][:800]}" for i, s in enumerate(sources))
    try:
        client = _nvidia_client()
        response = client.chat.completions.create(
            model=settings.nvidia_model,
            max_tokens=500,
            temperature=0.2,
            messages=[
                {"role": "system", "content": _DRAFT_PROMPT},
                {"role": "user", "content": f"TOPIC: {topic}\n\nEVIDENCE:\n{evidence_block}"},
            ],
        )
        return (response.choices[0].message.content or "").strip()
    except Exception as exc:
        return f"(Drafting failed: {exc})"


def run_research_job(job_id: str, case_id: str, topic: str) -> None:
    """The full pipeline. Runs synchronously -- called from a FastAPI
    BackgroundTask, which Starlette automatically runs in a worker thread."""
    log = lambda msg: database.append_research_log(job_id, msg)  # noqa: E731

    try:
        database.update_research_job(job_id, status="running")
        log(f'Expanding "{topic}" into search queries…')
        queries = expand_queries(topic)
        log("Queries: " + "; ".join(queries))

        seen_urls: set[str] = set()
        candidates: list[dict] = []
        for q in queries:
            log(f"Searching: {q}")
            found = list(web_search(q, settings.research_results_per_query))
            if settings.research_use_academic_archives:
                found.extend(academic_search(q, settings.research_results_per_query))
            for r in found:
                if r["url"] not in seen_urls:
                    seen_urls.add(r["url"])
                    candidates.append(r)
            if len(candidates) >= settings.research_max_sources * 2:
                break  # already have plenty of candidates to try fetching

        ingested_sources: list[dict] = []  # for the LLM draft step: {title, text}
        source_records: list[dict] = []  # for the job result: {doc_id, title, url, source_type}
        retriever = get_retriever(case_id)

        for r in candidates:
            if len(ingested_sources) >= settings.research_max_sources:
                break

            source_type = r.get("source_type", "web")
            direct_text = r.get("direct_text")
            if direct_text and len(direct_text) >= 200:
                # arXiv/patent abstracts fetched from their own API -- more reliable
                # than re-scraping the page, so skip the HTTP fetch entirely.
                log(f"Using {source_type} abstract directly: {r['title']}")
                title, text = r["title"], direct_text
            else:
                log(f"Fetching ({source_type}): {r['url']}")
                title, text = fetch_readable_text(r["url"])
                if not text:
                    log(f"  skipped (couldn't extract usable text)")
                    continue

            display_title = title or r["title"] or r["url"]
            doc_id = str(uuid.uuid4())

            retriever.add_documents([(doc_id, display_title, text)])
            n_chunks = len(chunk_document(doc_id, display_title, text, settings.max_chunk_sentences))
            database.save_document(case_id, doc_id, f"{display_title} (via research: {r['url']})", text, n_chunks)

            ingested_sources.append({"title": display_title, "text": text})
            source_records.append(
                {"doc_id": doc_id, "title": display_title, "url": r["url"], "source_type": source_type}
            )
            log(f"  indexed as \"{display_title}\" ({n_chunks} chunks, source: {source_type})")

        if not ingested_sources:
            database.update_research_job(
                job_id,
                status="error",
                error="No usable sources were found or fetched for this topic. Try a more specific topic, or add sources manually in the Library.",
                sources=[],
            )
            log("No usable sources found -- stopping.")
            return

        log(f"Drafting a grounded paragraph from {len(ingested_sources)} source(s)…")
        draft = draft_from_evidence(topic, ingested_sources)

        database.update_research_job(job_id, status="done", draft_text=draft, sources=source_records)
        log("Done.")

    except Exception as exc:  # last-resort safety net so a job never hangs at "running" forever
        database.update_research_job(job_id, status="error", error=str(exc))
        log(f"Failed: {exc}")
