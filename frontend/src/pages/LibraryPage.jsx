import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import CorpusUpload from '../components/CorpusUpload.jsx'
import { useCase } from '../CaseContext.jsx'
import { corpusStatus, deleteDocument, getDocumentDetail, ingestCorpus, listDocuments } from '../api.js'

export default function LibraryPage() {
  const { activeCaseId, activeCase, loading: caseLoading } = useCase()

  const [docs, setDocs] = useState([])
  const [status, setStatus] = useState({ documents_indexed: 0, chunks_indexed: 0, document_titles: [] })
  const [expanded, setExpanded] = useState({}) // id -> full text (once fetched)
  const [busyId, setBusyId] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(false)

  useEffect(() => {
    setExpanded({})
    if (activeCaseId) refresh()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeCaseId])

  async function refresh() {
    setLoading(true)
    try {
      const [d, s] = await Promise.all([listDocuments(activeCaseId), corpusStatus(activeCaseId)])
      setDocs(d)
      setStatus(s)
      setError(false)
    } catch {
      setError(true)
    } finally {
      setLoading(false)
    }
  }

  async function handleIngest(documents) {
    await ingestCorpus(activeCaseId, documents)
    await refresh()
  }

  async function handleExpand(doc) {
    if (expanded[doc.id]) {
      setExpanded((prev) => ({ ...prev, [doc.id]: undefined }))
      return
    }
    const detail = await getDocumentDetail(activeCaseId, doc.id)
    setExpanded((prev) => ({ ...prev, [doc.id]: detail.text }))
  }

  async function handleDelete(doc) {
    if (!confirm(`Remove "${doc.title}" from the corpus? This deletes it permanently, including its search index entries.`)) {
      return
    }
    setBusyId(doc.id)
    try {
      await deleteDocument(activeCaseId, doc.id)
      await refresh()
    } finally {
      setBusyId(null)
    }
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
            <Link to="/cases">Create a case</Link> to start building a corpus.
          </p>
        </div>
      </main>
    )
  }

  return (
    <main className="page-single">
      <div className="page-header">
        <h2>Corpus Library</h2>
        <p className="muted page-intro">
          Sources for <strong>{activeCase?.name}</strong>. Every document you add is stored
          permanently (SQLite on the backend), so it's still here after a restart. {status.documents_indexed}{' '}
          document{status.documents_indexed === 1 ? '' : 's'}, {status.chunks_indexed} chunk
          {status.chunks_indexed === 1 ? '' : 's'} indexed.
        </p>
      </div>

      {error && <div className="banner-error">Can't reach the backend. Is the FastAPI server running?</div>}

      <CorpusUpload onIngest={handleIngest} status={status} />

      {loading ? (
        <p className="muted" style={{ marginTop: 20 }}>
          Loading corpus…
        </p>
      ) : docs.length === 0 ? (
        <p className="muted" style={{ marginTop: 20 }}>
          No documents yet — add your first trusted source above.
        </p>
      ) : (
        <div className="library-grid">
          {docs.map((doc) => (
            <div className="doc-card" key={doc.id}>
              <div className="doc-card-title">{doc.title}</div>
              <div className="doc-card-meta">
                {doc.chunk_count} chunk{doc.chunk_count === 1 ? '' : 's'} · added{' '}
                {new Date(doc.created_at).toLocaleDateString()}
              </div>
              <p className="doc-card-preview">{expanded[doc.id] || doc.preview}</p>
              <div className="doc-card-actions">
                <button className="btn-secondary" onClick={() => handleExpand(doc)}>
                  {expanded[doc.id] ? 'Show less' : 'Read full text'}
                </button>
                <button className="btn-danger" onClick={() => handleDelete(doc)} disabled={busyId === doc.id}>
                  {busyId === doc.id ? 'Removing…' : 'Remove'}
                </button>
              </div>
            </div>
          ))}
        </div>
      )}
    </main>
  )
}
