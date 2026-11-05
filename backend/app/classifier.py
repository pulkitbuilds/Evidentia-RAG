"""
LLM Judge (via NVIDIA NIM): decides whether a claim is SUPPORTED, CONTRADICTED,
or UNVERIFIED by the retrieved evidence chunks.

NVIDIA's NIM API (https://integrate.api.nvidia.com/v1) is OpenAI-compatible,
so we talk to it with the standard `openai` SDK, just pointed at a different
base_url and using an NVIDIA-hosted model id (e.g. "meta/llama-3.1-70b-instruct").
"""
from __future__ import annotations

import json

from openai import OpenAI

from app.config import settings
from app.models import Verdict

_SYSTEM_PROMPT = """You are a strict fact-checking judge. You are given a CLAIM (a single \
sentence from a document someone is writing) and a numbered list of EVIDENCE passages \
retrieved from a trusted corpus.

Decide the relationship between the claim and the evidence:
- "supported": at least one evidence passage directly supports the claim's factual content.
- "contradicted": at least one evidence passage directly contradicts the claim (states \
something incompatible with it). Contradicted takes priority over supported if both appear.
- "unverified": the evidence is irrelevant, off-topic, or insufficient to judge the claim \
either way. Also use this for claims that are not factual (opinions, questions, instructions).

Respond with ONLY a JSON object, no markdown fences, no preamble:
{
  "verdict": "supported" | "contradicted" | "unverified",
  "explanation": "one short sentence explaining why",
  "best_evidence_index": <int index of the most relevant evidence passage, or null if unverified>
}
"""


def _build_user_prompt(claim: str, evidence: list[dict]) -> str:
    if not evidence:
        return f'CLAIM: "{claim}"\n\nEVIDENCE: (no evidence retrieved)'
    lines = [f'CLAIM: "{claim}"', "", "EVIDENCE:"]
    for i, chunk in enumerate(evidence):
        lines.append(f'[{i}] (source: {chunk["doc_title"]}) {chunk["text"]}')
    return "\n".join(lines)


def _get_client() -> OpenAI:
    return OpenAI(api_key=settings.nvidia_api_key, base_url=settings.nvidia_base_url)


def classify_claim(claim: str, evidence: list[dict]) -> tuple[Verdict, str, int | None]:
    """Returns (verdict, explanation, best_evidence_index)."""
    client = _get_client()

    response = client.chat.completions.create(
        model=settings.nvidia_model,
        max_tokens=300,
        temperature=0.0,
        messages=[
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": _build_user_prompt(claim, evidence)},
        ],
    )

    raw_text = (response.choices[0].message.content or "").strip()
    raw_text = raw_text.removeprefix("```json").removeprefix("```").removesuffix("```").strip()

    try:
        parsed = json.loads(raw_text)
        verdict = Verdict(parsed["verdict"])
        explanation = parsed.get("explanation", "")
        best_idx = parsed.get("best_evidence_index")
    except (json.JSONDecodeError, KeyError, ValueError):
        # Fail safe: never crash the request over a malformed judge response.
        verdict = Verdict.UNVERIFIED
        explanation = "Judge response could not be parsed; treated as unverified."
        best_idx = None

    if not evidence:
        best_idx = None

    return verdict, explanation, best_idx
