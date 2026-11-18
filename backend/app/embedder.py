from __future__ import annotations

import math

from app.config import settings


def _l2_normalize(vec: list[float]) -> list[float]:
    norm = math.sqrt(sum(x * x for x in vec)) or 1.0
    return [x / norm for x in vec]


class LocalEmbedder:
    def __init__(self, model_name: str) -> None:
        from sentence_transformers import SentenceTransformer  # lazy: heavy, needs PyTorch

        self._model = SentenceTransformer(model_name)

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return self._model.encode(texts, normalize_embeddings=True).tolist()

    def embed_query(self, text: str) -> list[float]:
        return self._model.encode([text], normalize_embeddings=True).tolist()[0]


class NvidiaEmbedder:
    _BATCH = 32  # keep requests comfortably under typical NIM batch limits

    def __init__(self, model: str, api_key: str, base_url: str) -> None:
        from openai import OpenAI

        if not api_key or not api_key.strip():
            raise ValueError(
                "NVIDIA_API_KEY is missing. "
                "Configure NVIDIA_API_KEY in Streamlit Cloud Secrets."
            )

        if not base_url or not base_url.strip():
            raise ValueError("NVIDIA_BASE_URL is missing.")

        self._client = OpenAI(
            api_key=api_key.strip(),
            base_url=base_url.strip(),
        )
        self._model = model

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


def make_embedder():
    provider = settings.embedding_provider.strip().lower()
    if provider == "nvidia":
        return NvidiaEmbedder(settings.nvidia_embedding_model, settings.nvidia_api_key, settings.nvidia_base_url)
    if provider == "local":
        return LocalEmbedder(settings.embedding_model_name)
    raise ValueError(f"Unknown EMBEDDING_PROVIDER '{settings.embedding_provider}' (use 'local' or 'nvidia').")
