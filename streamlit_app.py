"""
Evidentia -- Streamlit edition.

Streamlit Community Cloud runs exactly one Streamlit script, so it can't host
the React frontend or the FastAPI server. This file is a standalone UI that
imports the same backend modules (auth, database, retrieval, classifier,
research, verifier) and calls them directly -- no HTTP layer involved.

Differences from the React/FastAPI version:
  * claims are checked when you press "Check claims", not live as you type
  * research runs in the foreground (you wait 30-90s) instead of as a background job
  * login lasts for the browser session; refreshing the page logs you out

Run locally:  streamlit run streamlit_app.py   (from the repo root)
"""
from __future__ import annotations

import os
import sys
import uuid
from pathlib import Path

# ChromaDB needs SQLite >= 3.35, which is newer than Streamlit Cloud's system SQLite.
try:
    __import__("pysqlite3")
    sys.modules["sqlite3"] = sys.modules.pop("pysqlite3")
except ImportError:
    pass

import streamlit as st

st.set_page_config(page_title="Evidentia", page_icon="📑", layout="wide")

# Streamlit secrets -> environment variables, BEFORE the backend config is imported.
try:
    for _key, _val in st.secrets.items():
        if isinstance(_val, (str, int, float, bool)):
            os.environ.setdefault(str(_key).upper(), str(_val))
except Exception:
    pass  # no secrets file (e.g. local run); fall back to .env / real environment

os.environ.setdefault("EMBEDDING_PROVIDER", "nvidia")  # PyTorch is too heavy for Community Cloud
os.environ.setdefault("JWT_SECRET", "unused-in-streamlit-edition")  # sessions use st.session_state, not JWTs
sys.path.insert(0, str(Path(__file__).parent / "backend"))

from app import auth, database, research, verifier  # noqa: E402
from app.chunking import chunk_document, split_sentences  # noqa: E402
from app.classifier import classify_claim  # noqa: E402
from app.config import settings  # noqa: E402
from app.retrieval import drop_case_retriever, get_retriever  # noqa: E402

MAX_SENTENCES_PER_CHECK = 25  # bounds LLM/API cost for one button press
VERDICT_STYLE = {"supported": ("green", "✓"), "contradicted": ("red", "✕"), "unverified": ("gray", "—")}
SOURCE_LABEL = {"web": "Web", "arxiv": "arXiv paper", "crossref": "Published paper", "patent": "Patent"}


@st.cache_resource
def _init_db() -> bool:
    database.init_db()
    return True


@st.cache_resource(show_spinner="Loading this case's search index…")
def _ready_retriever(case_id: str):
    """Chroma/BM25 are derived indexes; rebuild them from the database once per
    server process (container disks are ephemeral, the database is not)."""
    retriever = get_retriever(case_id)
    docs = database.get_documents_for_case(case_id)
    if docs:
        retriever.rebuild_from_documents(docs)
    return retriever


def _esc(text: str) -> str:
    return text.replace("]", "\\]")


# ---------------------------------------------------------------- auth

def _auth_screen() -> None:
    st.title("Evidentia")
    st.caption("Evidence-first research & writing")
    login_tab, register_tab = st.tabs(["Log in", "Create account"])

    with login_tab:
        with st.form("login"):
            email = st.text_input("Email")
            password = st.text_input("Password", type="password")
            submitted = st.form_submit_button("Log in")
        if submitted:
            user = database.get_user_by_email(email.strip().lower())
            if user and auth.verify_password(password, user["password_hash"]):
                st.session_state["user"] = {"id": user["id"], "email": user["email"]}
                st.rerun()
            else:
                st.error("Incorrect email or password.")

    with register_tab:
        with st.form("register"):
            email = st.text_input("Email", key="reg_email")
            password = st.text_input("Password (8+ characters)", type="password", key="reg_pw")
            submitted = st.form_submit_button("Create account")
        if submitted:
            email = email.strip().lower()
            if "@" not in email or "." not in email.split("@")[-1]:
                st.error("That doesn't look like a valid email address.")
            elif len(password) < 8:
                st.error("Password must be at least 8 characters.")
            elif database.get_user_by_email(email):
                st.error("An account with that email already exists.")
            else:
                user_id = str(uuid.uuid4())
                database.create_user(user_id, email, auth.hash_password(password))
                database.create_case(str(uuid.uuid4()), user_id, "My First Case")
                st.session_state["user"] = {"id": user_id, "email": email}
                st.rerun()


# ---------------------------------------------------------------- sidebar / cases

def _create_case_cb(user_id: str) -> None:
    name = st.session_state.get("new_case_name", "").strip()
    if name:
        case_id = str(uuid.uuid4())
        database.create_case(case_id, user_id, name)
        st.session_state["active_case"] = case_id
        st.session_state["new_case_name"] = ""


def _delete_case_cb(case_id: str) -> None:
    if st.session_state.get("confirm_delete"):
        database.delete_case(case_id)
        drop_case_retriever(case_id)
        st.session_state.pop("active_case", None)
        st.session_state["confirm_delete"] = False


def _sidebar(user: dict) -> tuple[str, str]:
    with st.sidebar:
        st.markdown(f"**{user['email']}**")
        if st.button("Log out"):
            st.session_state.clear()
            st.rerun()
        st.divider()

        cases = database.list_cases(user["id"])
        if not cases:
            database.create_case(str(uuid.uuid4()), user["id"], "My First Case")
            cases = database.list_cases(user["id"])
        options = {c["id"]: c["name"] for c in cases}
        if st.session_state.get("active_case") not in options:
            st.session_state["active_case"] = next(iter(options))

        case_id = st.selectbox("Case file", list(options), format_func=lambda i: options[i], key="active_case")

        with st.expander("New / delete case"):
            st.text_input("New case name", key="new_case_name")
            st.button("Create case", on_click=_create_case_cb, args=(user["id"],))
            st.checkbox("I understand deleting removes its documents and history", key="confirm_delete")
            st.button("Delete this case", on_click=_delete_case_cb, args=(case_id,))
    return case_id, options[case_id]


# ---------------------------------------------------------------- draft

def _check_sentence(case_id: str, sentence: str, context: str | None) -> dict:
    retriever = _ready_retriever(case_id)
    best_idx = None
    try:
        evidence = retriever.search(f"{context} {sentence}" if context else sentence)
        if not evidence or evidence[0]["merged_score"] < settings.min_relevance_score:
            verdict, explanation, evidence = "unverified", "No sufficiently relevant evidence found in the corpus.", []
        else:
            v, explanation, best_idx = classify_claim(sentence, evidence)
            verdict = v.value
    except Exception as exc:  # one failed API call shouldn't sink the whole batch
        verdict, explanation, evidence = "unverified", f"Check failed: {exc}", []

    best = None
    if evidence:
        best = evidence[best_idx] if best_idx is not None and 0 <= best_idx < len(evidence) else evidence[0]
    database.save_claim_check(
        case_id=case_id,
        sentence=sentence,
        verdict=verdict,
        explanation=explanation,
        best_doc_title=best["doc_title"] if best else None,
        best_evidence_text=best["text"] if best else None,
        merged_score=best["merged_score"] if best else None,
    )
    return {"sentence": sentence, "verdict": verdict, "explanation": explanation, "best": best}


def draft_tab(case_id: str) -> None:
    st.text_area(
        "Your draft",
        key="draft_text",
        height=220,
        placeholder="Write or paste text here, then press “Check claims”.",
    )
    if st.button("Check claims", type="primary"):
        if not database.get_documents_for_case(case_id):
            st.warning("This case has no sources yet — add some in the Library tab first.")
        else:
            sentences = [s for s in split_sentences(st.session_state.get("draft_text", "")) if len(s) > 3]
            if len(sentences) > MAX_SENTENCES_PER_CHECK:
                st.info(f"Checking the first {MAX_SENTENCES_PER_CHECK} of {len(sentences)} sentences.")
                sentences = sentences[:MAX_SENTENCES_PER_CHECK]
            results, bar = [], st.progress(0.0, text="Checking claims…")
            for i, sentence in enumerate(sentences):
                context = sentences[i - 1] if i > 0 else None
                results.append(_check_sentence(case_id, sentence, context))
                bar.progress((i + 1) / len(sentences), text=f"Checked {i + 1} of {len(sentences)}")
            bar.empty()
            st.session_state["draft_results"] = {"case_id": case_id, "results": results}

    saved = st.session_state.get("draft_results")
    if not saved or saved["case_id"] != case_id or not saved["results"]:
        return
    results = saved["results"]
    counts = {v: sum(1 for r in results if r["verdict"] == v) for v in VERDICT_STYLE}
    cols = st.columns(4)
    cols[0].metric("Grounded", f"{round(100 * counts['supported'] / len(results))}%")
    cols[1].metric("Supported", counts["supported"])
    cols[2].metric("Contradicted", counts["contradicted"])
    cols[3].metric("Unverified", counts["unverified"])
    st.divider()
    for r in results:
        color, mark = VERDICT_STYLE[r["verdict"]]
        st.markdown(f":{color}[{mark} {_esc(r['sentence'])}]")
        with st.expander("Why / source"):
            st.write(r["explanation"])
            if r["best"]:
                st.caption(f"Source: {r['best']['doc_title']} (match {r['best']['merged_score']:.2f})")
                st.write(r["best"]["text"])


# ---------------------------------------------------------------- library

def _ingest(case_id: str, docs: list[tuple[str, str]]) -> int:
    retriever = _ready_retriever(case_id)
    triples = [(str(uuid.uuid4()), title, text) for title, text in docs if text.strip()]
    if not triples:
        return 0
    retriever.add_documents(triples)
    for doc_id, title, text in triples:
        n_chunks = len(chunk_document(doc_id, title, text, settings.max_chunk_sentences))
        database.save_document(case_id, doc_id, title, text, n_chunks)
    return len(triples)


def library_tab(case_id: str) -> None:
    docs = database.list_documents(case_id)
    with st.expander("Add sources", expanded=not docs):
        with st.form("upload_form", clear_on_submit=True):
            files = st.file_uploader("Upload .txt / .md files", type=["txt", "md"], accept_multiple_files=True)
            up = st.form_submit_button("Add uploaded files")
        if up and files:
            with st.spinner("Indexing…"):
                n = _ingest(case_id, [(f.name, f.getvalue().decode("utf-8", errors="ignore")) for f in files])
            st.success(f"Added {n} document(s).")
            st.rerun()

        with st.form("paste_form", clear_on_submit=True):
            title = st.text_input("Title")
            text = st.text_area("Pasted source text", height=160)
            pasted = st.form_submit_button("Add pasted text")
        if pasted:
            if title.strip() and text.strip():
                with st.spinner("Indexing…"):
                    _ingest(case_id, [(title.strip(), text)])
                st.rerun()
            else:
                st.warning("Give the pasted text a title and some content.")

    if not docs:
        st.caption("No documents yet.")
        return
    st.caption(f"{len(docs)} document(s)")
    for d in docs:
        with st.expander(f"{d['title']} — {d['chunk_count']} chunk(s)"):
            full = database.get_document(case_id, d["id"])
            st.write(full["text"] if full else d["preview"])
            if st.button("Remove", key=f"del_{d['id']}"):
                database.delete_document(case_id, d["id"])
                _ready_retriever(case_id).remove_document(d["id"])
                st.rerun()


# ---------------------------------------------------------------- research

def _insert_draft_cb(text: str) -> None:
    st.session_state["draft_text"] = text
    st.toast("Draft inserted — switch to the Draft tab.")


def _show_job(job: dict) -> None:
    st.markdown(f"**{job['status'].upper()}** — {job['topic']}")
    if job["log"]:
        st.code("\n".join(job["log"]), language=None)
    if job["error"]:
        st.error(job["error"])
    for s in job["sources"]:
        st.markdown(f"- `{SOURCE_LABEL.get(s.get('source_type', 'web'), 'Web')}` [{s['title']}]({s['url']})")
    if job["draft_text"]:
        st.subheader("Drafted paragraph")
        st.info(job["draft_text"])
        st.button("Insert into Draft", on_click=_insert_draft_cb, args=(job["draft_text"],), key=f"ins_{job['id']}")


def research_tab(case_id: str) -> None:
    st.caption("Searches the web plus arXiv, CrossRef and (best-effort) patents, adds the sources to this case, and drafts a starting paragraph.")
    topic = st.text_input("Topic or question", key="research_topic")
    if st.button("Start research", type="primary", disabled=not topic.strip()):
        _ready_retriever(case_id)  # make sure the index is loaded before research adds to it
        job_id = str(uuid.uuid4())
        database.create_research_job(job_id, case_id, topic.strip())
        with st.spinner("Researching — usually 30–90 seconds. Keep this tab open."):
            research.run_research_job(job_id, case_id, topic.strip())
        st.session_state["last_job"] = job_id

    job_id = st.session_state.get("last_job")
    job = database.get_research_job(job_id) if job_id else None
    if job and job["case_id"] == case_id:
        _show_job(job)

    past = [j for j in database.list_research_jobs(case_id, 10) if not job or j["id"] != job["id"]]
    if past:
        with st.expander("Past research in this case"):
            for j in past:
                st.markdown(f"- **{j['status']}** — {j['topic']} ({len(j['sources'])} source(s))")


# ---------------------------------------------------------------- verify

def verify_tab() -> None:
    st.caption("Checks whether a URL or DOI is a real, registered publication (via CrossRef) and whether its domain looks scholarly or official. It checks provenance, not whether a claim inside is true.")
    source = st.text_input("URL or DOI", placeholder="https://doi.org/10.xxxx/xxxxx  or  10.xxxx/xxxxx")
    if st.button("Check source", disabled=not source.strip()):
        with st.spinner("Checking…"):
            result = verifier.verify_source(source.strip())
        banner = {"likely_genuine": st.success, "plausible": st.success, "unverified": st.warning, "retracted": st.error}
        banner.get(result["verdict"], st.info)(f"{result['verdict'].replace('_', ' ').title()}: {result['recommendation']}")
        for reason in result["reasons"]:
            st.markdown(f"- {reason}")
        if result["metadata"]:
            st.json(result["metadata"])


# ---------------------------------------------------------------- case log

def log_tab(case_id: str) -> None:
    entries = database.list_claim_checks(case_id, 200)
    if not entries:
        st.caption("No claims checked yet.")
        return
    for e in entries:
        color, mark = VERDICT_STYLE.get(e["verdict"], ("gray", "—"))
        st.markdown(f":{color}[{mark} {_esc(e['sentence'])}]")
        meta = e["created_at"][:16].replace("T", " ")
        if e["best_doc_title"]:
            meta += f" · {e['best_doc_title']}"
        st.caption(f"{meta}" + (f" — {e['explanation']}" if e["explanation"] else ""))


# ---------------------------------------------------------------- main

def main() -> None:
    _init_db()
    if "user" not in st.session_state:
        _auth_screen()
        return

    case_id, case_name = _sidebar(st.session_state["user"])
    st.title("Evidentia")
    st.caption(f"Case: {case_name}")

    draft, library, research_t, verify, log = st.tabs(["Draft", "Library", "Research", "Verify Source", "Case Log"])
    with draft:
        draft_tab(case_id)
    with library:
        library_tab(case_id)
    with research_t:
        research_tab(case_id)
    with verify:
        verify_tab()
    with log:
        log_tab(case_id)


main()
