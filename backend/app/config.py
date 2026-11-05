"""
Central configuration for RAGnarok backend.
Loads from environment variables / .env via pydantic-settings.
"""
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # --- NVIDIA NIM (OpenAI-compatible) ---
    nvidia_api_key: str = ""
    nvidia_base_url: str = "https://integrate.api.nvidia.com/v1"
    nvidia_model: str = "meta/llama-3.1-70b-instruct"

    # --- Embeddings ---
    embedding_provider: str = "local"  # "local" (sentence-transformers) or "nvidia" (hosted, no PyTorch)
    embedding_model_name: str = "BAAI/bge-small-en-v1.5"  # used when provider=local
    nvidia_embedding_model: str = "nvidia/nv-embedqa-e5-v5"  # used when provider=nvidia

    # --- Storage ---
    chroma_persist_dir: str = "./data/chroma"
    collection_name: str = "ragnarok_corpus"
    database_url: str = "sqlite:///./data/ragnarok.db"

    # --- Retrieval ---
    top_k: int = 5
    dense_weight: float = 0.6
    sparse_weight: float = 0.4
    # A claim is UNVERIFIED if the best merged retrieval score is below this
    min_relevance_score: float = 0.15

    # --- Chunking ---
    max_chunk_sentences: int = 3

    # --- Research assistant ---
    research_max_queries: int = 4        # how many search queries to expand a topic into
    research_results_per_query: int = 3  # web results to consider per query
    research_max_sources: int = 6        # total pages to actually fetch + ingest, across all queries
    research_fetch_timeout: int = 15     # seconds, per page fetch
    research_max_chars_per_source: int = 6000  # truncate long pages before chunking/indexing
    research_use_academic_archives: bool = True  # also query arXiv/CrossRef/PatentsView, not just web search

    # --- Academic archive search (all optional; search works without these) ---
    crossref_mailto: str = ""  # set to your email to use CrossRef's faster "polite pool"
    patentsview_api_key: str = ""  # PatentsView has shifted between keyless and key-required access

    # --- Server ---
    cors_origins: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]
    # Optional regex, e.g. https://evidentia-.*\\.vercel\\.app to also allow Vercel preview URLs
    cors_origin_regex: str = ""

    # --- Auth ---
    # CHANGE THIS in your .env for any real deployment -- this default is only
    # safe for local, single-machine use. Anyone who knows this secret can
    # forge login tokens for any user.
    jwt_secret: str = "change-this-secret-in-production"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60 * 24 * 7  # 1 week


settings = Settings()

if settings.jwt_secret == "change-this-secret-in-production":
    import sys

    print(
        "\n[RAGnarok] WARNING: JWT_SECRET is still the default value. "
        "Set a real random secret in backend/.env before deploying anywhere "
        "other than your own machine (e.g. `python -c \"import secrets; print(secrets.token_hex(32))\"`).\n",
        file=sys.stderr,
    )
