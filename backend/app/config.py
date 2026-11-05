
"""
Central configuration for RAGnarok backend.

Loads configuration from:
1. Environment variables
2. .env file
3. Streamlit Cloud secrets (st.secrets)

Environment variables take priority over Streamlit secrets.
"""

from typing import Any

from pydantic_settings import (
    BaseSettings,
    SettingsConfigDict,
    PydanticBaseSettingsSource,
)


def streamlit_secrets_source() -> dict[str, Any]:
    """
    Read configuration from Streamlit Cloud secrets.

    Returns an empty dictionary when Streamlit is unavailable
    or secrets cannot be accessed.
    """
    try:
        import streamlit as st

        secrets = st.secrets
        return dict(secrets)

    except Exception:
        return {}


class Settings(BaseSettings):

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:

        def streamlit_source(settings: BaseSettings) -> dict[str, Any]:
            return streamlit_secrets_source()

        return (
            init_settings,
            env_settings,
            dotenv_settings,
            streamlit_source,
            file_secret_settings,
        )

    # ---------------- NVIDIA NIM ----------------

    nvidia_api_key: str = ""
    nvidia_base_url: str = "https://integrate.api.nvidia.com/v1"
    nvidia_model: str = "meta/llama-3.1-70b-instruct"

    # ---------------- Embeddings ----------------

    embedding_provider: str = "local"

    embedding_model_name: str = "BAAI/bge-small-en-v1.5"
    nvidia_embedding_model: str = "nvidia/nv-embedqa-e5-v5"

    # ---------------- Storage ----------------

    chroma_persist_dir: str = "./data/chroma"
    collection_name: str = "ragnarok_corpus"
    database_url: str = "sqlite:///./data/ragnarok.db"

    # ---------------- Retrieval ----------------

    top_k: int = 5
    dense_weight: float = 0.6
    sparse_weight: float = 0.4
    min_relevance_score: float = 0.15

    # ---------------- Chunking ----------------

    max_chunk_sentences: int = 3

    # ---------------- Research Assistant ----------------

    research_max_queries: int = 4
    research_results_per_query: int = 3
    research_max_sources: int = 6
    research_fetch_timeout: int = 15
    research_max_chars_per_source: int = 6000
    research_use_academic_archives: bool = True

    # ---------------- Academic Archives ----------------

    crossref_mailto: str = ""
    patentsview_api_key: str = ""

    # ---------------- Server ----------------

    cors_origins: list[str] = [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ]

    cors_origin_regex: str = ""

    # ---------------- Authentication ----------------

    jwt_secret: str = "change-this-secret-in-production"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60 * 24 * 7


# Initialize settings once
settings = Settings()


# ---------------- Configuration Validation ----------------

if settings.jwt_secret == "change-this-secret-in-production":
    import sys

    print(
        "\n[RAGnarok] WARNING: JWT_SECRET is still using the default value. "
        "Set a secure JWT_SECRET before deploying.\n",
        file=sys.stderr,
    )

if settings.embedding_provider.lower() == "nvidia":
    if not settings.nvidia_api_key.strip():
        raise ValueError(
            "NVIDIA_API_KEY is missing. "
            "Configure it in Streamlit Cloud Secrets or your .env file."
        )

    if not settings.nvidia_base_url.strip():
        raise ValueError("NVIDIA_BASE_URL is missing.")
