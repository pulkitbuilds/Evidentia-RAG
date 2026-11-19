from __future__ import annotations

import logging
import math

from app.config import settings

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _l2_normalize(vec: list[float]) -> list[float]:
    norm = math.sqrt(sum(x * x for x in vec)) or 1.0
    return [x / norm for x in vec]


# ---------------------------------------------------------------------------
# Embedder implementations
# ---------------------------------------------------------------------------

class LocalEmbedder:
    """CPU-based sentence-transformers embedder. Zero API dependencies."""

    def __init__(self, model_name: str) -> None:
        from sentence_transformers import SentenceTransformer  # lazy: needs PyTorch
        logger.info("Loading local embedding model '%s'…", model_name)
        self._model = SentenceTransformer(model_name)

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return self._model.encode(
            texts, normalize_embeddings=True, batch_size=64, show_progress_bar=False
        ).tolist()

    def embed_query(self, text: str) -> list[float]:
        return self._model.encode([text], normalize_embeddings=True).tolist()[0]


class NvidiaEmbedder:
    """NVIDIA NIM hosted embeddings (OpenAI-compatible API)."""
    _BATCH = 32  # keep requests under typical NIM batch limits

    def __init__(self, model: str, api_key: str, base_url: str) -> None:
        from openai import OpenAI

        if not api_key or not api_key.strip():
            raise ValueError("NVIDIA_API_KEY is missing. Set NVIDIA_API_KEY in .env.")
        if not base_url or not base_url.strip():
            raise ValueError("NVIDIA_BASE_URL is missing.")

        self._client = OpenAI(api_key=api_key.strip(), base_url=base_url.strip())
        self._model = model
        logger.info("NvidiaEmbedder ready (model=%s).", model)

    def _embed(self, texts: list[str], input_type: str) -> list[list[float]]:
        out: list[list[float]] = []
        for i in range(0, len(texts), self._BATCH):
            batch = texts[i : i + self._BATCH]
            resp = self._client.embeddings.create(
                model=self._model,
                input=batch,
                encoding_format="float",
                # NVIDIA retrieval models distinguish stored passages from queries
                extra_body={"input_type": input_type, "truncate": "END"},
            )
            for item in sorted(resp.data, key=lambda d: d.index):
                out.append(_l2_normalize(list(item.embedding)))
        return out

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return self._embed(texts, "passage") if texts else []

    def embed_query(self, text: str) -> list[float]:
        return self._embed([text], "query")[0]


class GeminiEmbedder:
    """Google Gemini text-embedding-004 (or whichever model is configured)."""
    _BATCH = 100  # Gemini batch endpoint supports up to 100 items

    def __init__(self, model: str, api_key: str) -> None:
        if not api_key or not api_key.strip():
            raise ValueError("GEMINI_API_KEY is missing. Set GEMINI_API_KEY in .env.")
        import google.generativeai as genai  # lazy import
        genai.configure(api_key=api_key.strip())
        self._genai = genai
        self._model = model
        logger.info("GeminiEmbedder ready (model=%s).", model)

    def _embed_batch(self, texts: list[str], task_type: str) -> list[list[float]]:
        out: list[list[float]] = []
        for i in range(0, len(texts), self._BATCH):
            batch = texts[i : i + self._BATCH]
            result = self._genai.embed_content(
                model=self._model,
                content=batch,
                task_type=task_type,
            )
            embeddings = result.get("embedding", []) if isinstance(result, dict) else result["embedding"]
            # embed_content returns a list of vectors when given a list
            if isinstance(embeddings[0], float):
                # Single text returned as flat list — wrap it
                out.append(_l2_normalize(embeddings))
            else:
                for vec in embeddings:
                    out.append(_l2_normalize(vec))
        return out

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        return self._embed_batch(texts, "retrieval_document")

    def embed_query(self, text: str) -> list[float]:
        result = self._genai.embed_content(
            model=self._model,
            content=text,
            task_type="retrieval_query",
        )
        vec = result.get("embedding", []) if isinstance(result, dict) else result["embedding"]
        return _l2_normalize(vec)


class FallbackEmbedder:
    """Wraps a primary embedder and silently falls back to a secondary on any error.

    This lets you configure NVIDIA or Gemini as primary and always have local
    as a guaranteed last resort — without crashing document ingestion.
    """

    def __init__(self, primary, fallback, primary_name: str = "primary", fallback_name: str = "fallback") -> None:
        self._primary = primary
        self._fallback = fallback
        self._primary_name = primary_name
        self._fallback_name = fallback_name

    def _run_with_fallback(self, method: str, *args):
        try:
            return getattr(self._primary, method)(*args)
        except Exception as exc:
            logger.warning(
                "%s embedder failed (%s); falling back to %s.",
                self._primary_name, exc, self._fallback_name,
            )
            return getattr(self._fallback, method)(*args)

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return self._run_with_fallback("embed_documents", texts)

    def embed_query(self, text: str) -> list[float]:
        return self._run_with_fallback("embed_query", text)


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def _make_local() -> LocalEmbedder:
    return LocalEmbedder(settings.embedding_model_name)


def make_embedder():
    """Build the embedder from config.

    Priority order when EMBEDDING_PROVIDER is set:
      nvidia  → NvidiaEmbedder with LocalEmbedder fallback
      gemini  → GeminiEmbedder  with LocalEmbedder fallback
      local   → LocalEmbedder (no fallback needed)

    Any provider that fails to initialise (bad key, missing package) also
    falls back to LocalEmbedder automatically.
    """
    provider = settings.embedding_provider.strip().lower()

    if provider == "nvidia":
        try:
            primary = NvidiaEmbedder(
                settings.nvidia_embedding_model,
                settings.nvidia_api_key,
                settings.nvidia_base_url,
            )
            return FallbackEmbedder(primary, _make_local(), "nvidia", "local")
        except Exception as exc:
            logger.warning("NvidiaEmbedder init failed (%s); using local embedder.", exc)
            return _make_local()

    if provider == "gemini":
        try:
            primary = GeminiEmbedder(settings.gemini_embedding_model, settings.gemini_api_key)
            return FallbackEmbedder(primary, _make_local(), "gemini", "local")
        except Exception as exc:
            logger.warning("GeminiEmbedder init failed (%s); using local embedder.", exc)
            return _make_local()

    if provider == "local":
        return _make_local()

    logger.warning("Unknown EMBEDDING_PROVIDER '%s'; defaulting to local.", settings.embedding_provider)
    return _make_local()
