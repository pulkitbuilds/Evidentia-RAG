"""
RAGnarok backend entrypoint.

    Source Corpus -> chunk -> Embed+Index -> Hybrid Retrieval -> LLM Judge -> Verdict

Everything above happens *within a case* -- a case is a separate project
(e.g. "Q3 Report", "Thesis Ch. 2") with its own corpus, its own search index,
and its own history -- and every case belongs to exactly one logged-in user.
SQLite (app/database.py) is the durable source of truth for users, cases,
documents, and checks: everything is saved there, and on startup each case's
search index (Chroma + BM25) is rebuilt from it, so it all survives a server
restart.

Run with:  uvicorn app.main:app --reload
"""
import datetime as dt
import uuid

from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app import auth, database, research, verifier
from app.chunking import chunk_document
from app.classifier import classify_claim
from app.config import settings
from app.models import (
    CaseCreateRequest,
    CaseListResponse,
    CaseRecord,
    CaseRenameRequest,
    ClaimCheckRequest,
    ClaimCheckResponse,
    ClaimLogResponse,
    CorpusStatus,
    DocumentDetail,
    DocumentListResponse,
    DocumentRecord,
    EvidenceChunk,
    IngestRequest,
    IngestResponse,
    LoginRequest,
    RegisterRequest,
    ResearchJobListResponse,
    ResearchJobRecord,
    ResearchStartRequest,
    ResearchStartResponse,
    ScoreRequest,
    ScoreResponse,
    TokenResponse,
    UserOut,
    Verdict,
    VerifySourceRequest,
    VerifySourceResponse,
)
from app.retrieval import drop_case_retriever, get_retriever

app = FastAPI(title="Evidentia: Evidence-First Research & Writing Platform", version="0.5.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_origin_regex=settings.cors_origin_regex or None,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

_security = HTTPBearer(auto_error=False)


def get_current_user(credentials: HTTPAuthorizationCredentials | None = Depends(_security)) -> dict:
    """FastAPI dependency: extracts and validates the Bearer token, returns
    the current user's row as a dict. Raises 401 for anything wrong -- no
    token, malformed token, expired token, or a token for a deleted user."""
    if credentials is None:
        raise HTTPException(status_code=401, detail="Not authenticated.")
    user_id = auth.decode_token(credentials.credentials)
    if user_id is None:
        raise HTTPException(status_code=401, detail="Invalid or expired token.")
    user = database.get_user_by_id(user_id)
    if user is None:
        raise HTTPException(status_code=401, detail="User no longer exists.")
    return user


def _require_owned_case(case_id: str, user: dict) -> None:
    """404 (not 403) for both 'case doesn't exist' and 'case exists but isn't
    yours' -- deliberately not distinguishing the two, so a valid case_id for
    someone else's case can't be discovered by probing this endpoint."""
    owner_id = database.get_case_owner(case_id)
    if owner_id is None or owner_id != user["id"]:
        raise HTTPException(status_code=404, detail="Case not found.")


def _now_iso() -> str:
    return dt.datetime.utcnow().isoformat()


@app.on_event("startup")
def on_startup() -> None:
    database.init_db()
    # Rebuild every case's search index (Chroma + BM25) from SQLite, across
    # every user. Done at startup up front, rather than lazily per-request,
    # so the very first claim check against any case isn't slowed down by it.
    for case in database.list_all_cases():
        stored_docs = database.get_documents_for_case(case["id"])
        if stored_docs:
            get_retriever(case["id"]).rebuild_from_documents(stored_docs)


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


# ---------------- Auth ----------------

@app.post("/auth/register", response_model=TokenResponse)
def register(request: RegisterRequest) -> TokenResponse:
    email = request.email.strip().lower()
    if "@" not in email or "." not in email.split("@")[-1]:
        raise HTTPException(status_code=400, detail="That doesn't look like a valid email address.")
    if database.get_user_by_email(email) is not None:
        raise HTTPException(status_code=409, detail="An account with that email already exists.")

    user_id = str(uuid.uuid4())
    database.create_user(user_id, email, auth.hash_password(request.password))

    # Give a brand-new account one case to start in, rather than an empty
    # app with nowhere to put a document.
    database.create_case(str(uuid.uuid4()), user_id, "My First Case")

    token = auth.create_access_token(user_id)
    return TokenResponse(access_token=token, user=UserOut(id=user_id, email=email))


@app.post("/auth/login", response_model=TokenResponse)
def login(request: LoginRequest) -> TokenResponse:
    email = request.email.strip().lower()
    user = database.get_user_by_email(email)
    if user is None or not auth.verify_password(request.password, user["password_hash"]):
        # Same message for "no such user" and "wrong password" -- don't leak
        # which emails have accounts.
        raise HTTPException(status_code=401, detail="Incorrect email or password.")

    token = auth.create_access_token(user["id"])
    return TokenResponse(access_token=token, user=UserOut(id=user["id"], email=user["email"]))


@app.get("/auth/me", response_model=UserOut)
def get_me(current_user: dict = Depends(get_current_user)) -> UserOut:
    return UserOut(id=current_user["id"], email=current_user["email"])


# ---------------- Cases ----------------

@app.post("/cases", response_model=CaseRecord)
def create_case(request: CaseCreateRequest, current_user: dict = Depends(get_current_user)) -> CaseRecord:
    case_id = str(uuid.uuid4())
    database.create_case(case_id, current_user["id"], request.name.strip())
    return CaseRecord(id=case_id, name=request.name.strip(), created_at=_now_iso(), document_count=0, check_count=0)


@app.get("/cases", response_model=CaseListResponse)
def list_cases(current_user: dict = Depends(get_current_user)) -> CaseListResponse:
    return CaseListResponse(cases=[CaseRecord(**c) for c in database.list_cases(current_user["id"])])


@app.patch("/cases/{case_id}", response_model=dict)
def rename_case(case_id: str, request: CaseRenameRequest, current_user: dict = Depends(get_current_user)) -> dict:
    _require_owned_case(case_id, current_user)
    database.rename_case(case_id, request.name.strip())
    return {"renamed": True}


@app.delete("/cases/{case_id}")
def delete_case(case_id: str, current_user: dict = Depends(get_current_user)) -> dict:
    _require_owned_case(case_id, current_user)
    database.delete_case(case_id)
    drop_case_retriever(case_id)
    return {"deleted": True}


# ---------------- Corpus (scoped to a case) ----------------

@app.post("/cases/{case_id}/corpus/ingest", response_model=IngestResponse)
def ingest_corpus(case_id: str, request: IngestRequest, current_user: dict = Depends(get_current_user)) -> IngestResponse:
    _require_owned_case(case_id, current_user)
    if not request.documents:
        raise HTTPException(status_code=400, detail="No documents provided.")

    retriever = get_retriever(case_id)
    docs = [(d.id, d.title, d.text) for d in request.documents]
    chunks_indexed = retriever.add_documents(docs)

    # Persist to SQLite so this document survives a backend restart.
    for d in request.documents:
        n_chunks = len(chunk_document(d.id, d.title, d.text, settings.max_chunk_sentences))
        database.save_document(case_id, d.id, d.title, d.text, n_chunks)

    return IngestResponse(documents_ingested=len(request.documents), chunks_indexed=chunks_indexed)


@app.get("/cases/{case_id}/corpus/status", response_model=CorpusStatus)
def corpus_status(case_id: str, current_user: dict = Depends(get_current_user)) -> CorpusStatus:
    _require_owned_case(case_id, current_user)
    retriever = get_retriever(case_id)
    return CorpusStatus(
        documents_indexed=retriever.num_documents,
        chunks_indexed=retriever.num_chunks,
        document_titles=retriever.document_titles,
    )


@app.get("/cases/{case_id}/corpus/documents", response_model=DocumentListResponse)
def list_documents(case_id: str, current_user: dict = Depends(get_current_user)) -> DocumentListResponse:
    _require_owned_case(case_id, current_user)
    rows = database.list_documents(case_id)
    return DocumentListResponse(documents=[DocumentRecord(**r) for r in rows])


@app.get("/cases/{case_id}/corpus/documents/{doc_id}", response_model=DocumentDetail)
def get_document(case_id: str, doc_id: str, current_user: dict = Depends(get_current_user)) -> DocumentDetail:
    _require_owned_case(case_id, current_user)
    row = database.get_document(case_id, doc_id)
    if not row:
        raise HTTPException(status_code=404, detail="Document not found.")
    return DocumentDetail(**row)


@app.delete("/cases/{case_id}/corpus/documents/{doc_id}")
def delete_document(case_id: str, doc_id: str, current_user: dict = Depends(get_current_user)) -> dict:
    _require_owned_case(case_id, current_user)
    existed = database.delete_document(case_id, doc_id)
    if not existed:
        raise HTTPException(status_code=404, detail="Document not found.")
    removed_chunks = get_retriever(case_id).remove_document(doc_id)
    return {"deleted": True, "chunks_removed": removed_chunks}


# ---------------- Claim checking (scoped to a case) ----------------

@app.post("/cases/{case_id}/claims/check", response_model=ClaimCheckResponse)
def check_claim(case_id: str, request: ClaimCheckRequest, current_user: dict = Depends(get_current_user)) -> ClaimCheckResponse:
    _require_owned_case(case_id, current_user)
    sentence = request.sentence.strip()
    if not sentence:
        raise HTTPException(status_code=400, detail="Empty sentence.")

    retriever = get_retriever(case_id)

    # Retrieve using the sentence itself; fold in light context to disambiguate
    # pronouns ("it", "this") without diluting the query too much.
    query = sentence if not request.context else f"{request.context.strip()} {sentence}"
    raw_evidence = retriever.search(query)

    best_idx: int | None = None
    if not raw_evidence or raw_evidence[0]["merged_score"] < settings.min_relevance_score:
        verdict = Verdict.UNVERIFIED
        explanation = "No sufficiently relevant evidence found in the corpus."
        evidence_chunks: list[dict] = []
    else:
        verdict, explanation, best_idx = classify_claim(sentence, raw_evidence)
        evidence_chunks = raw_evidence

    evidence_models = [EvidenceChunk(**e) for e in evidence_chunks]
    best_evidence = None
    if evidence_models:
        if best_idx is not None and 0 <= best_idx < len(evidence_models):
            best_evidence = evidence_models[best_idx]
        else:
            best_evidence = evidence_models[0]

    # Log every check to SQLite, powering the Case Log / history page.
    database.save_claim_check(
        case_id=case_id,
        sentence=sentence,
        verdict=verdict.value,
        explanation=explanation,
        best_doc_title=best_evidence.doc_title if best_evidence else None,
        best_evidence_text=best_evidence.text if best_evidence else None,
        merged_score=best_evidence.merged_score if best_evidence else None,
    )

    return ClaimCheckResponse(
        sentence=sentence,
        verdict=verdict,
        explanation=explanation,
        best_evidence=best_evidence,
        evidence=evidence_models,
    )


@app.get("/cases/{case_id}/history/checks", response_model=ClaimLogResponse)
def get_history(case_id: str, limit: int = 100, current_user: dict = Depends(get_current_user)) -> ClaimLogResponse:
    _require_owned_case(case_id, current_user)
    rows = database.list_claim_checks(case_id, limit=limit)
    return ClaimLogResponse(checks=rows)


# ---------------- Research assistant (scoped to a case) ----------------

@app.post("/cases/{case_id}/research", response_model=ResearchStartResponse)
def start_research(
    case_id: str,
    request: ResearchStartRequest,
    background_tasks: BackgroundTasks,
    current_user: dict = Depends(get_current_user),
) -> ResearchStartResponse:
    _require_owned_case(case_id, current_user)
    job_id = str(uuid.uuid4())
    database.create_research_job(job_id, case_id, request.topic.strip())
    # Starlette runs a sync background task in a worker thread automatically,
    # so this doesn't block the response -- the frontend polls the job below.
    background_tasks.add_task(research.run_research_job, job_id, case_id, request.topic.strip())
    return ResearchStartResponse(job_id=job_id)


@app.get("/cases/{case_id}/research/{job_id}", response_model=ResearchJobRecord)
def get_research_job(case_id: str, job_id: str, current_user: dict = Depends(get_current_user)) -> ResearchJobRecord:
    _require_owned_case(case_id, current_user)
    row = database.get_research_job(job_id)
    if not row or row["case_id"] != case_id:
        raise HTTPException(status_code=404, detail="Research job not found.")
    return ResearchJobRecord(**row)


@app.get("/cases/{case_id}/research", response_model=ResearchJobListResponse)
def list_research_jobs(case_id: str, limit: int = 20, current_user: dict = Depends(get_current_user)) -> ResearchJobListResponse:
    _require_owned_case(case_id, current_user)
    rows = database.list_research_jobs(case_id, limit=limit)
    return ResearchJobListResponse(jobs=[ResearchJobRecord(**r) for r in rows])


# ---------------- Source verifier (stateless, not case-scoped) ----------------

@app.post("/verify-source", response_model=VerifySourceResponse)
def verify_source(request: VerifySourceRequest, current_user: dict = Depends(get_current_user)) -> VerifySourceResponse:
    result = verifier.verify_source(request.source.strip())
    return VerifySourceResponse(**result)


# ---------------- Document-level scoring (stateless, not case-scoped) ----------------

@app.post("/document/score", response_model=ScoreResponse)
def score_document(request: ScoreRequest) -> ScoreResponse:
    total = len(request.verdicts)
    supported = sum(1 for v in request.verdicts if v == Verdict.SUPPORTED)
    contradicted = sum(1 for v in request.verdicts if v == Verdict.CONTRADICTED)
    unverified = sum(1 for v in request.verdicts if v == Verdict.UNVERIFIED)

    grounding_score = (supported / total) if total else 0.0

    return ScoreResponse(
        total_claims=total,
        supported=supported,
        contradicted=contradicted,
        unverified=unverified,
        grounding_score=round(grounding_score, 4),
    )
