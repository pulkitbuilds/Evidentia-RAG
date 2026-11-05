import { useEffect, useRef, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { useCase } from '../CaseContext.jsx'
import { getResearchJob, listResearchJobs, startResearch } from '../api.js'

const POLL_MS = 2000

const SOURCE_TYPE_LABEL = {
  web: 'Web',
  arxiv: 'arXiv paper',
  crossref: 'Published paper',
  patent: 'Patent',
}

const STATUS_LABEL = {
  queued: 'Queued',
  running: 'Researching…',
  done: 'Done',
  error: 'Error',
}

export default function ResearchPage() {
  const { activeCaseId, activeCase, loading: caseLoading } = useCase()
  const navigate = useNavigate()

  const [topic, setTopic] = useState('')
  const [job, setJob] = useState(null)
  const [starting, setStarting] = useState(false)
  const [pastJobs, setPastJobs] = useState([])
  const pollRef = useRef(null)

  useEffect(() => {
    setJob(null)
    if (activeCaseId) refreshPastJobs()
    return () => clearInterval(pollRef.current)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeCaseId])

  async function refreshPastJobs() {
    try {
      const jobs = await listResearchJobs(activeCaseId, 10)
      setPastJobs(jobs)
    } catch {
      // non-fatal -- the page still works without job history
    }
  }

  function pollJob(jobId) {
    clearInterval(pollRef.current)
    pollRef.current = setInterval(async () => {
      try {
        const data = await getResearchJob(activeCaseId, jobId)
        setJob(data)
        if (data.status === 'done' || data.status === 'error') {
          clearInterval(pollRef.current)
          refreshPastJobs()
        }
      } catch {
        clearInterval(pollRef.current)
      }
    }, POLL_MS)
  }

  async function handleStart() {
    if (!topic.trim()) return
    setStarting(true)
    try {
      const { job_id } = await startResearch(activeCaseId, topic.trim())
      setJob({ id: job_id, status: 'queued', log: [], sources: [], draft_text: null, error: null, topic: topic.trim() })
      pollJob(job_id)
    } finally {
      setStarting(false)
    }
  }

  function handleInsertDraft() {
    if (!job?.draft_text) return
    navigate('/', { state: { insertText: job.draft_text } })
  }

  if (caseLoading) {
    return <p className="muted" style={{ marginTop: 20 }}>Loading…</p>
  }

  if (!activeCaseId) {
    return (
      <main className="page-single">
        <div className="page-header">
          <h2>No case selected</h2>
          <p className="muted page-intro">
            <Link to="/cases">Create a case</Link> to run research into it.
          </p>
        </div>
      </main>
    )
  }

  const isActive = job && (job.status === 'queued' || job.status === 'running')

  return (
    <main className="page-single">
      <div className="page-header">
        <h2>Research Assistant</h2>
        <p className="muted page-intro">
          Give it a topic or question. It expands that into search queries, fetches web sources,
          adds them straight to <strong>{activeCase?.name}</strong>'s corpus, and drafts a first
          paragraph grounded only in what it found — a starting point you can then edit and
          re-verify on the Draft page like anything else.
        </p>
      </div>

      <div className="case-create-row">
        <input
          className="title-input"
          placeholder="e.g. Effects of remote work on commercial office vacancy rates"
          value={topic}
          onChange={(e) => setTopic(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && !isActive && handleStart()}
          disabled={isActive || starting}
        />
        <button onClick={handleStart} disabled={isActive || starting || !topic.trim()}>
          {starting || isActive ? 'Researching…' : 'Start Research'}
        </button>
      </div>

      {job && (
        <div className="research-result">
          <div className="research-status-row">
            <span className={`status-badge status-${job.status}`}>{STATUS_LABEL[job.status] || job.status}</span>
            <span className="muted">"{job.topic}"</span>
          </div>

          {job.log?.length > 0 && (
            <div className="research-log">
              {job.log.map((line, i) => (
                <div key={i} className="research-log-line">
                  {line}
                </div>
              ))}
            </div>
          )}

          {job.status === 'error' && <div className="banner-error">{job.error}</div>}

          {job.status === 'done' && (
            <>
              {job.sources?.length > 0 && (
                <>
                  <h3 className="preview-label">Sources added to corpus</h3>
                  <div className="library-grid">
                    {job.sources.map((s) => (
                      <div className="doc-card" key={s.doc_id}>
                        <span className={`source-type-tag source-type-${s.source_type || 'web'}`}>
                          {SOURCE_TYPE_LABEL[s.source_type] || 'Web'}
                        </span>
                        <div className="doc-card-title">{s.title}</div>
                        <a href={s.url} target="_blank" rel="noreferrer" className="doc-card-meta research-source-link">
                          {s.url}
                        </a>
                      </div>
                    ))}
                  </div>
                </>
              )}

              {job.draft_text && (
                <>
                  <h3 className="preview-label">Drafted paragraph</h3>
                  <div className="research-draft">
                    <p>{job.draft_text}</p>
                  </div>
                  <button onClick={handleInsertDraft}>Insert into Draft</button>
                </>
              )}
            </>
          )}
        </div>
      )}

      {pastJobs.length > 0 && (
        <>
          <h3 className="preview-label" style={{ marginTop: 32 }}>
            Past research in this case
          </h3>
          <div className="log-list">
            {pastJobs
              .filter((j) => j.id !== job?.id)
              .map((j) => (
                <div className={`log-entry verdict-${j.status === 'done' ? 'supported' : j.status === 'error' ? 'contradicted' : 'unverified'}`} key={j.id}>
                  <div className="log-meta">
                    <span>{STATUS_LABEL[j.status] || j.status}</span>
                    <span>{new Date(j.created_at).toLocaleString()}</span>
                  </div>
                  <p className="log-sentence">&ldquo;{j.topic}&rdquo;</p>
                  {j.sources?.length > 0 && (
                    <p className="log-source">{j.sources.length} source(s) added</p>
                  )}
                </div>
              ))}
          </div>
        </>
      )}
    </main>
  )
}
