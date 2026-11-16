"""
Persistent storage: Postgres (Supabase) via SQLAlchemy. Falls back to SQLite
for local dev when DATABASE_URL is a sqlite:// URL.

Five tables:
  users         - registered accounts. Every case belongs to exactly one user.
  cases         - your separate projects/case files (e.g. "Q3 Report",
                   "Thesis Ch. 2"), scoped to the user who created them.
                   Everything below belongs to exactly one case.
  documents     - every source document ever ingested, scoped to a case.
                   This is the durable "source of truth" for a case's corpus.
  claim_checks  - a running log of every sentence ever checked and its
                   verdict, scoped to a case.
  research_jobs - a log of autonomous research runs (topic -> web search ->
                   fetched sources -> drafted paragraph), scoped to a case.

Chunks themselves are *derived* from `documents` (via chunking.py) and live in
ChromaDB + an in-memory BM25 index, one pair of indexes per case. rank_bm25
has no persistence of its own, so on every backend startup we rebuild the
BM25 index (and re-sync Chroma) for every case from whatever is in the
`documents` table here. That's why `documents` -- not Chroma -- is the real
source of truth for "what's in a case's corpus."

NOTE ON SCHEMA CHANGES: this project has no migration system (no Alembic).
The tables are created by supabase_schema.sql (or by init_db() as a fallback).
init_db() never alters existing tables, so when you add a column, run an
ALTER TABLE in the Supabase SQL Editor and update the model below to match.
"""
import datetime as dt
import json
from pathlib import Path

from sqlalchemy import (
    Column,
    DateTime,
    Float,
    Integer,
    String,
    Text,
    create_engine,
    func,
)
from sqlalchemy.orm import declarative_base, sessionmaker
from sqlalchemy.pool import NullPool

from app.config import settings


# ============================================================
# DATABASE CONFIGURATION  (driven by DATABASE_URL in backend/.env)
# ============================================================

BACKEND_DIR = Path(__file__).resolve().parents[1]

# ChromaDB still persists here, so keep the folder even when using Postgres.
DATA_DIR = BACKEND_DIR / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)

DATABASE_URL = settings.database_url.strip()

# Supabase / Heroku-style URLs use postgres:// or postgresql://.
# SQLAlchemy needs the driver name to pick psycopg v3 (psycopg[binary]).
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql+psycopg://", 1)
elif DATABASE_URL.startswith("postgresql://"):
    DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+psycopg://", 1)

IS_SQLITE = DATABASE_URL.startswith("sqlite")

if IS_SQLITE:
    # Resolve the default relative path against backend/, not the cwd.
    if DATABASE_URL.startswith("sqlite:///./"):
        DATABASE_URL = f"sqlite:///{(BACKEND_DIR / DATABASE_URL[len('sqlite:///./'):]).as_posix()}"
    engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
elif ":6543" in DATABASE_URL:
    # Supabase transaction pooler (serverless, e.g. Vercel): no prepared
    # statements, and let the pooler own the connections.
    engine = create_engine(
        DATABASE_URL,
        poolclass=NullPool,
        connect_args={"prepare_threshold": None},
    )
else:
    # Supabase session pooler (port 5432) or direct connection.
    engine = create_engine(
        DATABASE_URL,
        pool_pre_ping=True,
        pool_size=5,
        max_overflow=5,
        pool_recycle=1800,
    )

SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    autocommit=False,
)

Base = declarative_base()


class UserRow(Base):
    __tablename__ = "users"

    id = Column(String, primary_key=True)
    email = Column(String, unique=True, index=True, nullable=False)
    password_hash = Column(String, nullable=False)
    created_at = Column(DateTime, default=lambda: dt.datetime.now(dt.UTC))


class CaseRow(Base):
    __tablename__ = "cases"

    id = Column(String, primary_key=True)
    user_id = Column(String, index=True, nullable=False)
    name = Column(String, nullable=False)
    created_at = Column(DateTime, default=lambda: dt.datetime.now(dt.UTC))


class DocumentRow(Base):
    __tablename__ = "documents"

    id = Column(String, primary_key=True)
    case_id = Column(String, index=True, nullable=False)
    title = Column(String, nullable=False)
    text = Column(Text, nullable=False)
    chunk_count = Column(Integer, default=0)
    created_at = Column(DateTime, default=lambda: dt.datetime.now(dt.UTC))


class ClaimCheckRow(Base):
    __tablename__ = "claim_checks"

    id = Column(Integer, primary_key=True, autoincrement=True)
    case_id = Column(String, index=True, nullable=False)
    sentence = Column(Text, nullable=False)
    verdict = Column(String, nullable=False)
    explanation = Column(Text, default="")
    best_doc_title = Column(String, nullable=True)
    best_evidence_text = Column(Text, nullable=True)
    merged_score = Column(Float, nullable=True)
    created_at = Column(DateTime, default=lambda: dt.datetime.now(dt.UTC))


class ResearchJobRow(Base):
    __tablename__ = "research_jobs"

    id = Column(String, primary_key=True)
    case_id = Column(String, index=True, nullable=False)
    topic = Column(Text, nullable=False)
    status = Column(String, nullable=False, default="queued")  # queued|running|done|error
    log = Column(Text, default="")  # newline-joined progress messages
    draft_text = Column(Text, nullable=True)
    sources_json = Column(Text, nullable=True)  # json list of {doc_id, title, url}
    error = Column(Text, nullable=True)
    created_at = Column(DateTime, default=lambda: dt.datetime.now(dt.UTC))
    updated_at = Column(DateTime, default=lambda: dt.datetime.now(dt.UTC), onupdate=lambda: dt.datetime.now(dt.UTC))


def init_db() -> None:
    Base.metadata.create_all(engine)


# ---------- users ----------

def create_user(user_id: str, email: str, password_hash: str) -> None:
    with SessionLocal() as session:
        session.add(UserRow(id=user_id, email=email, password_hash=password_hash))
        session.commit()


def get_user_by_email(email: str) -> dict | None:
    with SessionLocal() as session:
        r = session.query(UserRow).filter(UserRow.email == email).first()
        if not r:
            return None
        return {"id": r.id, "email": r.email, "password_hash": r.password_hash}


def get_user_by_id(user_id: str) -> dict | None:
    with SessionLocal() as session:
        r = session.get(UserRow, user_id)
        if not r:
            return None
        return {"id": r.id, "email": r.email, "password_hash": r.password_hash}


# ---------- cases ----------

def create_case(case_id: str, user_id: str, name: str) -> None:
    with SessionLocal() as session:
        session.add(CaseRow(id=case_id, user_id=user_id, name=name))
        session.commit()


def case_exists(case_id: str) -> bool:
    with SessionLocal() as session:
        return session.get(CaseRow, case_id) is not None


def get_case_owner(case_id: str) -> str | None:
    with SessionLocal() as session:
        row = session.get(CaseRow, case_id)
        return row.user_id if row else None


def list_cases(user_id: str) -> list[dict]:
    """Each case belonging to user_id, plus lightweight stats, for the Cases
    page and the header switcher."""
    with SessionLocal() as session:
        rows = (
            session.query(CaseRow)
            .filter(CaseRow.user_id == user_id)
            .order_by(CaseRow.created_at.asc())
            .all()
        )
        result = []
        for r in rows:
            doc_count = session.query(func.count(DocumentRow.id)).filter(DocumentRow.case_id == r.id).scalar()
            check_count = session.query(func.count(ClaimCheckRow.id)).filter(ClaimCheckRow.case_id == r.id).scalar()
            result.append(
                {
                    "id": r.id,
                    "name": r.name,
                    "created_at": r.created_at.isoformat(),
                    "document_count": doc_count or 0,
                    "check_count": check_count or 0,
                }
            )
        return result


def list_all_cases() -> list[dict]:
    """Unfiltered, across every user -- used only at backend startup to
    rebuild every case's search index. Never expose this over the API."""
    with SessionLocal() as session:
        rows = session.query(CaseRow).all()
        return [{"id": r.id} for r in rows]


def rename_case(case_id: str, name: str) -> bool:
    with SessionLocal() as session:
        row = session.get(CaseRow, case_id)
        if not row:
            return False
        row.name = name
        session.commit()
        return True


def delete_case(case_id: str) -> bool:
    """Cascades: deletes the case's documents, claim_checks, and research_jobs too."""
    with SessionLocal() as session:
        row = session.get(CaseRow, case_id)
        if not row:
            return False
        session.query(DocumentRow).filter(DocumentRow.case_id == case_id).delete()
        session.query(ClaimCheckRow).filter(ClaimCheckRow.case_id == case_id).delete()
        session.query(ResearchJobRow).filter(ResearchJobRow.case_id == case_id).delete()
        session.delete(row)
        session.commit()
        return True


# ---------- documents ----------

def save_document(case_id: str, doc_id: str, title: str, text: str, chunk_count: int) -> None:
    with SessionLocal() as session:
        existing = session.get(DocumentRow, doc_id)
        if existing:
            existing.title = title
            existing.text = text
            existing.chunk_count = chunk_count
        else:
            session.add(DocumentRow(id=doc_id, case_id=case_id, title=title, text=text, chunk_count=chunk_count))
        session.commit()


def list_documents(case_id: str) -> list[dict]:
    """Lightweight listing (with a short preview) for the Library page."""
    with SessionLocal() as session:
        rows = (
            session.query(DocumentRow)
            .filter(DocumentRow.case_id == case_id)
            .order_by(DocumentRow.created_at.desc())
            .all()
        )
        return [
            {
                "id": r.id,
                "title": r.title,
                "chunk_count": r.chunk_count,
                "created_at": r.created_at.isoformat(),
                "preview": (r.text[:220] + "…") if len(r.text) > 220 else r.text,
            }
            for r in rows
        ]


def get_document(case_id: str, doc_id: str) -> dict | None:
    """Full document (including full text), for viewing one document in detail."""
    with SessionLocal() as session:
        r = session.get(DocumentRow, doc_id)
        if not r or r.case_id != case_id:
            return None
        return {
            "id": r.id,
            "title": r.title,
            "text": r.text,
            "chunk_count": r.chunk_count,
            "created_at": r.created_at.isoformat(),
        }


def get_documents_for_case(case_id: str) -> list[tuple[str, str, str]]:
    """Returns (id, title, text) for every stored document in one case -- used
    to rebuild that case's search index from scratch at startup."""
    with SessionLocal() as session:
        rows = session.query(DocumentRow).filter(DocumentRow.case_id == case_id).all()
        return [(r.id, r.title, r.text) for r in rows]


def delete_document(case_id: str, doc_id: str) -> bool:
    with SessionLocal() as session:
        row = session.get(DocumentRow, doc_id)
        if not row or row.case_id != case_id:
            return False
        session.delete(row)
        session.commit()
        return True


# ---------- claim check log ----------

def save_claim_check(
    case_id: str,
    sentence: str,
    verdict: str,
    explanation: str,
    best_doc_title: str | None,
    best_evidence_text: str | None,
    merged_score: float | None,
) -> None:
    with SessionLocal() as session:
        session.add(
            ClaimCheckRow(
                case_id=case_id,
                sentence=sentence,
                verdict=verdict,
                explanation=explanation,
                best_doc_title=best_doc_title,
                best_evidence_text=best_evidence_text,
                merged_score=merged_score,
            )
        )
        session.commit()


def list_claim_checks(case_id: str, limit: int = 100) -> list[dict]:
    with SessionLocal() as session:
        rows = (
            session.query(ClaimCheckRow)
            .filter(ClaimCheckRow.case_id == case_id)
            .order_by(ClaimCheckRow.created_at.desc())
            .limit(limit)
            .all()
        )
        return [
            {
                "id": r.id,
                "sentence": r.sentence,
                "verdict": r.verdict,
                "explanation": r.explanation or "",
                "best_doc_title": r.best_doc_title,
                "best_evidence_text": r.best_evidence_text,
                "merged_score": r.merged_score,
                "created_at": r.created_at.isoformat(),
            }
            for r in rows
        ]


# ---------- research jobs ----------

def create_research_job(job_id: str, case_id: str, topic: str) -> None:
    with SessionLocal() as session:
        session.add(ResearchJobRow(id=job_id, case_id=case_id, topic=topic, status="queued", log=""))
        session.commit()


def append_research_log(job_id: str, message: str) -> None:
    with SessionLocal() as session:
        row = session.get(ResearchJobRow, job_id)
        if not row:
            return
        row.log = (row.log + "\n" + message) if row.log else message
        row.updated_at = dt.datetime.now(dt.UTC)
        session.commit()


def update_research_job(
    job_id: str,
    status: str | None = None,
    draft_text: str | None = None,
    sources: list[dict] | None = None,
    error: str | None = None,
) -> None:
    with SessionLocal() as session:
        row = session.get(ResearchJobRow, job_id)
        if not row:
            return
        if status is not None:
            row.status = status
        if draft_text is not None:
            row.draft_text = draft_text
        if sources is not None:
            row.sources_json = json.dumps(sources)
        if error is not None:
            row.error = error
        row.updated_at = dt.datetime.now(dt.UTC)
        session.commit()


def _research_job_to_dict(r: ResearchJobRow) -> dict:
    return {
        "id": r.id,
        "case_id": r.case_id,
        "topic": r.topic,
        "status": r.status,
        "log": r.log.split("\n") if r.log else [],
        "draft_text": r.draft_text,
        "sources": json.loads(r.sources_json) if r.sources_json else [],
        "error": r.error,
        "created_at": r.created_at.isoformat(),
        "updated_at": r.updated_at.isoformat(),
    }


def get_research_job(job_id: str) -> dict | None:
    with SessionLocal() as session:
        r = session.get(ResearchJobRow, job_id)
        return _research_job_to_dict(r) if r else None


def list_research_jobs(case_id: str, limit: int = 20) -> list[dict]:
    with SessionLocal() as session:
        rows = (
            session.query(ResearchJobRow)
            .filter(ResearchJobRow.case_id == case_id)
            .order_by(ResearchJobRow.created_at.desc())
            .limit(limit)
            .all()
        )
        return [_research_job_to_dict(r) for r in rows]
