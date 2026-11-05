"""
Hybrid retrieval: dense (ChromaDB / cosine over sentence-transformer embeddings)
merged with sparse (BM25Okapi keyword search):

    Dense Search (Chroma / cosine)      Sparse Search (BM25 / keyword)
                    \\                          /
                     merge + normalize + weight
                                |
                       Hybrid Retrieval (top-k)

Multi-case note: each case file gets its own isolated search index (its own
Chroma collection and its own in-memory BM25 index), so documents in one case
never leak into another case's retrieval results. The embedding model itself
(~130MB, slow to load) and the Chroma client/connection are expensive to set
up, so those are shared across every case via `RetrieverRegistry` -- only the
lightweight per-case index state (`HybridRetriever`) is duplicated.

Persistence note: Chroma's data lives on disk (settings.chroma_persist_dir)
and survives restarts on its own. rank_bm25, however, is a pure in-memory
index with no persistence -- so on every backend startup we rebuild BOTH the
in-memory chunk list and the BM25 index, per case, from SQLite (via
`rebuild_from_documents`, called once per case at startup in main.py). SQLite
is the real source of truth for "what's in each case's corpus"; Chroma and
BM25 are just derived search indexes over it.
"""
from __future__ import annotations

import re
import threading

import chromadb
from rank_bm25 import BM25Okapi

from app.chunking import Chunk, chunk_document
from app.config import settings
from app.embedder import make_embedder

_TOKEN_RE = re.compile(r"[a-z0-9]+")


def _tokenize(text: str) -> list[str]:
    return _TOKEN_RE.findall(text.lower())


def _normalize(scores: list[float]) -> list[float]:
    """Min-max normalize a list of scores into [0, 1]. Flat lists map to 0.5."""
    if not scores:
        return scores
    lo, hi = min(scores), max(scores)
    if hi - lo < 1e-9:
        return [0.5 for _ in scores]
    return [(s - lo) / (hi - lo) for s in scores]


class HybridRetriever:
    """
    Owns ONE case's corpus index (its Chroma collection + its in-memory BM25
    index) and exposes `search()` for the classifier to consume.

    Not thread-safe across writes; a simple lock guards re-indexing since a
    FastAPI app may serve concurrent requests.
    """

    def __init__(self, embedder, chroma_client: chromadb.ClientAPI, collection_name: str) -> None:
        self._lock = threading.Lock()
        self._embedder = embedder
        self._collection_name = collection_name
        self._chroma_client = chroma_client
        # Reuse the collection across restarts (rather than deleting it) so
        # the dense index survives a server restart, same as the SQLite corpus.
        self._collection = chroma_client.get_or_create_collection(
            name=collection_name,
            metadata={"hnsw:space": "cosine"},
        )

        self._chunks: list[Chunk] = []
        self._bm25: BM25Okapi | None = None
        self._doc_titles: dict[str, str] = {}

    # ---------- indexing ----------

    def _reindex_chunks(self, chunks: list[Chunk]) -> None:
        """(Re)builds the in-memory chunk list + BM25 index from `chunks`, and
        upserts them all into Chroma. Using upsert (rather than add) means this
        is safe to call repeatedly with overlapping ids -- existing entries are
        overwritten rather than causing a duplicate-id error."""
        self._chunks = chunks
        if chunks:
            embeddings = self._embedder.embed_documents([c.text for c in chunks])
            self._collection.upsert(
                ids=[c.chunk_id for c in chunks],
                documents=[c.text for c in chunks],
                embeddings=embeddings,
                metadatas=[{"doc_id": c.doc_id, "doc_title": c.doc_title} for c in chunks],
            )
            self._bm25 = BM25Okapi([_tokenize(c.text) for c in chunks])
        else:
            self._bm25 = None

    def rebuild_from_documents(self, documents: list[tuple[str, str, str]]) -> int:
        """Full reindex from a durable source (SQLite). Called once per case at
        backend startup to restore search state after a restart.
        documents: list of (doc_id, title, text)."""
        with self._lock:
            self._doc_titles = {doc_id: title for doc_id, title, _ in documents}
            all_chunks: list[Chunk] = []
            for doc_id, title, text in documents:
                all_chunks.extend(chunk_document(doc_id, title, text, settings.max_chunk_sentences))
            self._reindex_chunks(all_chunks)
            return len(all_chunks)

    def add_documents(self, documents: list[tuple[str, str, str]]) -> int:
        """documents: list of (doc_id, title, text). Returns number of NEW chunks indexed."""
        new_chunks: list[Chunk] = []
        for doc_id, title, text in documents:
            self._doc_titles[doc_id] = title
            new_chunks.extend(chunk_document(doc_id, title, text, settings.max_chunk_sentences))

        if not new_chunks:
            return 0

        with self._lock:
            self._reindex_chunks(self._chunks + new_chunks)

        return len(new_chunks)

    def remove_document(self, doc_id: str) -> int:
        """Removes every chunk belonging to doc_id. Returns how many chunks were removed."""
        with self._lock:
            removed_ids = [c.chunk_id for c in self._chunks if c.doc_id == doc_id]
            remaining = [c for c in self._chunks if c.doc_id != doc_id]
            if removed_ids:
                try:
                    self._collection.delete(ids=removed_ids)
                except Exception:
                    pass
            self._doc_titles.pop(doc_id, None)
            self._reindex_chunks(remaining)
            return len(removed_ids)

    def drop(self) -> None:
        """Deletes this case's entire Chroma collection. Called when the case itself is deleted."""
        try:
            self._chroma_client.delete_collection(self._collection_name)
        except Exception:
            pass

    @property
    def num_chunks(self) -> int:
        return len(self._chunks)

    @property
    def num_documents(self) -> int:
        return len(self._doc_titles)

    @property
    def document_titles(self) -> list[str]:
        return list(self._doc_titles.values())

    # ---------- search ----------

    def search(self, query: str, top_k: int | None = None) -> list[dict]:
        top_k = top_k or settings.top_k
        if not self._chunks or self._bm25 is None:
            return []

        # --- dense leg ---
        query_embedding = [self._embedder.embed_query(query)]
        dense_result = self._collection.query(
            query_embeddings=query_embedding,
            n_results=min(top_k * 3, len(self._chunks)),
        )
        # Chroma with cosine space returns a distance; similarity = 1 - distance
        dense_scores_by_id: dict[str, float] = {}
        for chunk_id, distance in zip(dense_result["ids"][0], dense_result["distances"][0]):
            dense_scores_by_id[chunk_id] = 1.0 - distance

        # --- sparse leg ---
        tokenized_query = _tokenize(query)
        bm25_scores = self._bm25.get_scores(tokenized_query)
        sparse_scores_by_id = {c.chunk_id: s for c, s in zip(self._chunks, bm25_scores)}

        # --- merge over the union of candidate ids, normalize each leg, weight ---
        candidate_ids = list(set(dense_scores_by_id) | set(sparse_scores_by_id))

        dense_raw = [dense_scores_by_id.get(cid, 0.0) for cid in candidate_ids]
        sparse_raw = [sparse_scores_by_id.get(cid, 0.0) for cid in candidate_ids]
        dense_norm = _normalize(dense_raw)
        sparse_norm = _normalize(sparse_raw)

        merged: list[dict] = []
        chunks_by_id = {c.chunk_id: c for c in self._chunks}
        for cid, d, s, d_raw, s_raw in zip(candidate_ids, dense_norm, sparse_norm, dense_raw, sparse_raw):
            merged_score = settings.dense_weight * d + settings.sparse_weight * s
            chunk = chunks_by_id[cid]
            merged.append(
                {
                    "doc_id": chunk.doc_id,
                    "doc_title": chunk.doc_title,
                    "text": chunk.text,
                    "dense_score": round(d_raw, 4),
                    "sparse_score": round(s_raw, 4),
                    "merged_score": round(merged_score, 4),
                }
            )

        merged.sort(key=lambda r: r["merged_score"], reverse=True)
        return merged[:top_k]


class RetrieverRegistry:
    """
    Holds one HybridRetriever per case, all sharing the same embedding model
    and Chroma client/connection (both expensive to set up, cheap to reuse).
    Retrievers are created lazily, on first use of a given case_id.
    """

    def __init__(self) -> None:
        self._setup_lock = threading.Lock()
        self._registry_lock = threading.Lock()
        self._embedder = None
        self._chroma_client: chromadb.ClientAPI | None = None
        self._retrievers: dict[str, HybridRetriever] = {}

    def _ensure_shared_resources(self) -> None:
        if self._embedder is not None:
            return
        with self._setup_lock:
            if self._embedder is None:
                self._embedder = make_embedder()
                self._chroma_client = chromadb.PersistentClient(path=settings.chroma_persist_dir)

    def get(self, case_id: str) -> HybridRetriever:
        self._ensure_shared_resources()
        if case_id not in self._retrievers:
            with self._registry_lock:
                if case_id not in self._retrievers:
                    # Different embedding providers produce different vector sizes, so they get separate collections.
                    provider_tag = "" if settings.embedding_provider.lower() == "local" else f"_{settings.embedding_provider.lower()}"
                    collection_name = f"{settings.collection_name}{provider_tag}_{case_id}"
                    self._retrievers[case_id] = HybridRetriever(self._embedder, self._chroma_client, collection_name)
        return self._retrievers[case_id]

    def drop_case(self, case_id: str) -> None:
        with self._registry_lock:
            retriever = self._retrievers.pop(case_id, None)
        if retriever is not None:
            retriever.drop()


# Module-level singleton, constructed lazily so importing this module (e.g. for
# tests) doesn't force-load the embedding model.
_registry = RetrieverRegistry()


def get_retriever(case_id: str) -> HybridRetriever:
    return _registry.get(case_id)


def drop_case_retriever(case_id: str) -> None:
    _registry.drop_case(case_id)
