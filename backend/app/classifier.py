from __future__ import annotations

import json
import logging

from openai import OpenAI

from app.config import settings
from app.models import Verdict

logger = logging.getLogger(__name__)

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


def _classify_via_gemini(claim: str, evidence: list[dict]) -> tuple[Verdict, str, int | None]:
    """Fallback: call Gemini when the NVIDIA call fails."""
    try:
        import google.generativeai as genai  # lazy import -- only needed on fallback

        genai.configure(api_key=settings.gemini_api_key)
        model = genai.GenerativeModel(
            model_name=settings.gemini_model,
            system_instruction=_SYSTEM_PROMPT,
        )
        response = model.generate_content(
            _build_user_prompt(claim, evidence),
            generation_config={"temperature": 0.0, "max_output_tokens": 300},
        )
        raw_text = (response.text or "").strip()
        raw_text = raw_text.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        parsed = json.loads(raw_text)
        verdict = Verdict(parsed["verdict"])
        explanation = parsed.get("explanation", "")
        best_idx = parsed.get("best_evidence_index")
        return verdict, explanation, best_idx
    except Exception as exc:
        logger.error("Gemini fallback also failed: %s", exc)
        return Verdict.UNVERIFIED, "Both NVIDIA and Gemini calls failed; treated as unverified.", None


def classify_claim(claim: str, evidence: list[dict]) -> tuple[Verdict, str, int | None]:
    """Returns (verdict, explanation, best_evidence_index).
    Tries NVIDIA first; falls back to Gemini if NVIDIA is unavailable or errors.
    """
    try:
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
            verdict = Verdict.UNVERIFIED
            explanation = "Judge response could not be parsed; treated as unverified."
            best_idx = None

    except Exception as exc:
        logger.warning("NVIDIA classify_claim failed (%s); falling back to Gemini.", exc)
        verdict, explanation, best_idx = _classify_via_gemini(claim, evidence)

    if not evidence:
        best_idx = None

    return verdict, explanation, best_idx
