import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { useCase } from '../CaseContext.jsx'
import { listHistory } from '../api.js'

const VERDICT_LABEL = {
  supported: 'Supported',
  contradicted: 'Contradicted',
  unverified: 'Unverified',
}

export default function HistoryPage() {
  const { activeCaseId, activeCase, loading: caseLoading } = useCase()

  const [entries, setEntries] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(false)

  useEffect(() => {
    if (!activeCaseId) return
    setLoading(true)
    listHistory(activeCaseId, 200)
      .then((data) => {
        setEntries(data)
        setError(false)
      })
      .catch(() => setError(true))
      .finally(() => setLoading(false))
  }, [activeCaseId])

  if (caseLoading) {
    return <p className="muted" style={{ marginTop: 20 }}>Loading…</p>
  }

  if (!activeCaseId) {
    return (
      <main className="page-single">
        <div className="page-header">
          <h2>No case selected</h2>
          <p className="muted page-intro">
            <Link to="/cases">Create a case</Link> to start a Case Log.
          </p>
        </div>
      </main>
    )
  }

  return (
    <main className="page-single">
      <div className="page-header">
        <h2>Case Log</h2>
        <p className="muted page-intro">
          Every claim ever checked in <strong>{activeCase?.name}</strong>, most recent first — a
          permanent audit trail of what's been verified and against what.
        </p>
      </div>

      {error && <div className="banner-error">Can't reach the backend. Is the FastAPI server running?</div>}

      {loading ? (
        <p className="muted">Loading case log…</p>
      ) : entries.length === 0 ? (
        <p className="muted">No claims checked yet — head to the Draft page and start writing.</p>
      ) : (
        <div className="log-list">
          {entries.map((e) => (
            <div className={`log-entry verdict-${e.verdict}`} key={e.id}>
              <div className="log-meta">
                <span>{VERDICT_LABEL[e.verdict]}</span>
                <span>{new Date(e.created_at).toLocaleString()}</span>
              </div>
              <p className="log-sentence">&ldquo;{e.sentence}&rdquo;</p>
              {e.explanation && <p className="log-explanation">{e.explanation}</p>}
              {e.best_doc_title && (
                <p className="log-source">
                  Source: <strong>{e.best_doc_title}</strong>
                  {e.merged_score != null && <span className="muted"> · match {e.merged_score.toFixed(2)}</span>}
                </p>
              )}
            </div>
          ))}
        </div>
      )}
    </main>
  )
}
