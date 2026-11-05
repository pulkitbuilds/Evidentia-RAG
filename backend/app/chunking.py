"""
Lightweight sentence-level chunker.

We deliberately avoid a heavy NLP dependency (spaCy/NLTK punkt download requires
network access at first run) and instead use a robust regex-based splitter with
a few guards for common abbreviations. Chunks are groups of `max_chunk_sentences`
consecutive sentences, so a claim's local context (e.g. a trailing clause) is
still retrievable.
"""
import re
from dataclasses import dataclass

_ABBREVIATIONS = {
    "mr.", "mrs.", "ms.", "dr.", "prof.", "sr.", "jr.", "vs.", "etc.",
    "e.g.", "i.e.", "fig.", "no.", "approx.", "u.s.", "u.k.", "st.",
}

_SENTENCE_BOUNDARY = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9\"'“])")


def split_sentences(text: str) -> list[str]:
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        return []

    raw_pieces = _SENTENCE_BOUNDARY.split(text)

    sentences: list[str] = []
    buffer = ""
    for piece in raw_pieces:
        candidate = (buffer + " " + piece).strip() if buffer else piece
        last_word = candidate.split(" ")[-1].lower() if candidate else ""
        if last_word in _ABBREVIATIONS:
            buffer = candidate
            continue
        sentences.append(candidate)
        buffer = ""
    if buffer:
        sentences.append(buffer)

    return [s.strip() for s in sentences if s.strip()]


@dataclass
class Chunk:
    chunk_id: str
    doc_id: str
    doc_title: str
    text: str


def chunk_document(doc_id: str, doc_title: str, text: str, max_sentences: int = 3) -> list[Chunk]:
    sentences = split_sentences(text)
    chunks: list[Chunk] = []
    for i in range(0, len(sentences), max_sentences):
        group = sentences[i : i + max_sentences]
        chunk_text = " ".join(group)
        chunk_id = f"{doc_id}::chunk::{i // max_sentences}"
        chunks.append(Chunk(chunk_id=chunk_id, doc_id=doc_id, doc_title=doc_title, text=chunk_text))
    return chunks
