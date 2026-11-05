import { useEffect, useState } from 'react'
import { Link, useLocation, useNavigate } from 'react-router-dom'
import Editor from '../components/Editor.jsx'
import CorpusUpload from '../components/CorpusUpload.jsx'
import ScorePanel from '../components/ScorePanel.jsx'
import EvidencePopover from '../components/EvidencePopover.jsx'
import { useCase } from '../CaseContext.jsx'
import { ingestCorpus, corpusStatus } from '../api.js'
import { splitSentences } from '../sentences.js'

export default function EditorPage() {
  const { activeCaseId, activeCase, loading: caseLoading } = useCase()
  const location = useLocation()
  const navigate = useNavigate()

  const [text, setText] = useState('')
  const [cache, setCache] = useState({}) // sentenceText -> ClaimCheckResponse
  const [status, setStatus] = useState({ documents_indexed: 0, chunks_indexed: 0, document_titles: [] })
  const [activeEvidence, setActiveEvidence] = useState(null)
  const [statusError, setStatusError] = useState(false)

  // Reset the draft + cache whenever the active case changes, so text/verdicts
  // from one case never bleed into another. If we just arrived here from the
  // Research page with a drafted paragraph, use that instead of a blank draft.
  useEffect(() => {
    setText('')
    setCache({})
    setActiveEvidence(null)
    if (activeCaseId) refreshStatus()

    if (location.state?.insertText) {
      setText(location.state.insertText)
      navigate('.', { replace: true, state: {} }) // consume it so it doesn't reappear later
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeCaseId])

  async function refreshStatus() {
    try {
      const s = await corpusStatus(activeCaseId)
      setStatus(s)
      setStatusError(false)
    } catch {
      setStatusError(true)
    }
  }

  async function handleIngest(documents) {
    await ingestCorpus(activeCaseId, documents)
    await refreshStatus()
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
            RAGnarok organizes your work into separate case files, each with its own corpus and
            history. <Link to="/cases">Create your first case</Link> to start writing.
          </p>
        </div>
      </main>
    )
  }

  const sentences = splitSentences(text)
  const resultsForScore = sentences
    .filter((s) => s.complete)
    .map((s) => ({ text: s.text, result: cache[s.text] }))

  return (
    <>
      <p className="active-case-strip">
        Writing in <strong>{activeCase?.name || '…'}</strong>
      </p>

      {statusError && (
        <div className="banner-error">
          Can't reach the backend at the configured API URL. Is the FastAPI server running?
        </div>
      )}

      <main className="app-grid">
        <div className="left-col">
          <CorpusUpload onIngest={handleIngest} status={status} />
        </div>

        <div className="center-col">
          <Editor
            text={text}
            setText={setText}
            cache={cache}
            setCache={setCache}
            onOpenEvidence={setActiveEvidence}
            corpusReady={status.chunks_indexed > 0}
            caseId={activeCaseId}
          />
        </div>

        <div className="right-col">
          <ScorePanel results={resultsForScore} />
          <div className="legend-note">
            <span className="dot supported" /> supported &nbsp;
            <span className="dot contradicted" /> contradicted &nbsp;
            <span className="dot unverified" /> unverified
            <p className="muted">Click any checked sentence to see its source.</p>
          </div>
        </div>
      </main>

      <EvidencePopover item={activeEvidence} onClose={() => setActiveEvidence(null)} />
    </>
  )
}
