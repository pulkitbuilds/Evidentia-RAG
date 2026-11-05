"""
Pydantic schemas shared across the API.
"""
from enum import Enum
from pydantic import BaseModel, Field


class Verdict(str, Enum):
    SUPPORTED = "supported"
    CONTRADICTED = "contradicted"
    UNVERIFIED = "unverified"


# ---------- Auth ----------

class RegisterRequest(BaseModel):
    email: str = Field(..., min_length=3, max_length=254)
    password: str = Field(..., min_length=8, max_length=128)


class LoginRequest(BaseModel):
    email: str = Field(..., min_length=3, max_length=254)
    password: str = Field(..., min_length=1, max_length=128)


class UserOut(BaseModel):
    id: str
    email: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut


# ---------- Cases ----------

class CaseCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)


class CaseRenameRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)


class CaseRecord(BaseModel):
    id: str
    name: str
    created_at: str
    document_count: int
    check_count: int


class CaseListResponse(BaseModel):
    cases: list[CaseRecord]


# ---------- Corpus ingestion ----------

class SourceDocument(BaseModel):
    id: str
    title: str
    text: str


class IngestRequest(BaseModel):
    documents: list[SourceDocument]


class IngestResponse(BaseModel):
    documents_ingested: int
    chunks_indexed: int


class CorpusStatus(BaseModel):
    documents_indexed: int
    chunks_indexed: int
    document_titles: list[str]


class DocumentRecord(BaseModel):
    id: str
    title: str
    chunk_count: int
    created_at: str
    preview: str


class DocumentListResponse(BaseModel):
    documents: list[DocumentRecord]


class DocumentDetail(BaseModel):
    id: str
    title: str
    text: str
    chunk_count: int
    created_at: str


# ---------- Claim checking ----------

class ClaimCheckRequest(BaseModel):
    sentence: str = Field(..., description="A single completed sentence typed by the user")
    context: str | None = Field(
        default=None, description="A few surrounding sentences, used only to disambiguate pronouns/refs"
    )


class EvidenceChunk(BaseModel):
    doc_id: str
    doc_title: str
    text: str
    dense_score: float
    sparse_score: float
    merged_score: float


class ClaimCheckResponse(BaseModel):
    sentence: str
    verdict: Verdict
    explanation: str
    best_evidence: EvidenceChunk | None
    evidence: list[EvidenceChunk]


# ---------- Document-level scoring ----------

class ScoreRequest(BaseModel):
    verdicts: list[Verdict]


class ScoreResponse(BaseModel):
    total_claims: int
    supported: int
    contradicted: int
    unverified: int
    grounding_score: float  # supported / total_claims, in [0, 1]


# ---------- History / case log ----------

class ClaimLogEntry(BaseModel):
    id: int
    sentence: str
    verdict: Verdict
    explanation: str
    best_doc_title: str | None
    best_evidence_text: str | None
    merged_score: float | None
    created_at: str


class ClaimLogResponse(BaseModel):
    checks: list[ClaimLogEntry]


# ---------- Research assistant ----------

class ResearchStartRequest(BaseModel):
    topic: str = Field(..., min_length=3, max_length=300)


class ResearchStartResponse(BaseModel):
    job_id: str


class ResearchSource(BaseModel):
    doc_id: str
    title: str
    url: str
    source_type: str = "web"  # web | arxiv | crossref | patent


class ResearchJobRecord(BaseModel):
    id: str
    case_id: str
    topic: str
    status: str  # queued | running | done | error
    log: list[str]
    draft_text: str | None
    sources: list[ResearchSource]
    error: str | None
    created_at: str
    updated_at: str


class ResearchJobListResponse(BaseModel):
    jobs: list[ResearchJobRecord]


# ---------- Source verifier ----------

class VerifySourceRequest(BaseModel):
    source: str = Field(..., min_length=3, max_length=500, description="A URL or a bare DOI")


class VerifySourceResponse(BaseModel):
    source: str
    verdict: str  # likely_genuine | plausible | unverified | retracted
    recommendation: str
    reasons: list[str]
    metadata: dict | None
