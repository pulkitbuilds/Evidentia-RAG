import { useState } from 'react'
import { verifySource } from '../api.js'

const VERDICT_LABEL = {
  likely_genuine: 'Likely Genuine',
  plausible: 'Plausible',
  unverified: 'Unverified',
  retracted: 'Retracted',
}

const VERDICT_CLASS = {
  likely_genuine: 'supported',
  plausible: 'supported',
  unverified: 'unverified',
  retracted: 'contradicted',
}

const BADGE_STATUS_CLASS = {
  likely_genuine: 'done',
  plausible: 'done',
  unverified: 'queued',
  retracted: 'error',
}

export default function VerifyPage() {
  const [source, setSource] = useState('')
  const [result, setResult] = useState(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  async function handleCheck() {
    if (!source.trim()) return
    setBusy(true)
    setError('')
    setResult(null)
    try {
      const data = await verifySource(source.trim())
      setResult(data)
    } catch (err) {
      setError(err.response?.data?.detail || 'Could not reach the backend.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <main className="page-single">
      <div className="page-header">
        <h2>Source Verifier</h2>
        <p className="muted page-intro">
          Paste a URL or a bare DOI (e.g. <code>10.1038/s41586-021-03491-6</code>). This checks
          whether it resolves to a real, registered publication (via CrossRef) and whether its
          domain matches known scholarly or official patterns — it checks the source's{' '}
          <em>provenance</em>, not whether any specific claim inside it is true. That part still
          goes through the Draft page against your case's corpus.
        </p>
      </div>

      <div className="case-create-row">
        <input
          className="title-input"
          placeholder="https://doi.org/10.xxxx/xxxxx or a 10.xxxx/xxxxx DOI"
          value={source}
          onChange={(e) => setSource(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && !busy && handleCheck()}
          disabled={busy}
        />
        <button onClick={handleCheck} disabled={busy || !source.trim()}>
          {busy ? 'Checking…' : 'Check Source'}
        </button>
      </div>

      {error && <div className="banner-error">{error}</div>}

      {result && (
        <div className="research-result">
          <div className="research-status-row">
            <span className={`status-badge status-${BADGE_STATUS_CLASS[result.verdict] || 'queued'}`}>
              {VERDICT_LABEL[result.verdict] || result.verdict}
            </span>
            <span className="muted">{result.source}</span>
          </div>

          <div className={`research-draft verdict-${VERDICT_CLASS[result.verdict]}`}>
            <p>{result.recommendation}</p>
          </div>

          {result.reasons?.length > 0 && (
            <>
              <h3 className="preview-label">Why</h3>
              <ul className="verify-reasons">
                {result.reasons.map((r, i) => (
                  <li key={i}>{r}</li>
                ))}
              </ul>
            </>
          )}

          {result.metadata && (
            <>
              <h3 className="preview-label">Resolved metadata</h3>
              <div className="evidence-block">
                {Object.entries(result.metadata).map(([k, v]) => (
                  <div key={k} className="verify-meta-row">
                    <span className="verify-meta-key">{k}</span>
                    <span>{String(v)}</span>
                  </div>
                ))}
              </div>
            </>
          )}
        </div>
      )}
    </main>
  )
}
