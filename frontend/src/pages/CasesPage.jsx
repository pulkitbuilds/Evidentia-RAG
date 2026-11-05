import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useCase } from '../CaseContext.jsx'
import { deleteCase, renameCase } from '../api.js'

export default function CasesPage() {
  const { cases, activeCaseId, setActiveCaseId, refreshCases, createAndSwitch, loading, error } = useCase()
  const navigate = useNavigate()

  const [newName, setNewName] = useState('')
  const [creating, setCreating] = useState(false)
  const [renamingId, setRenamingId] = useState(null)
  const [renameValue, setRenameValue] = useState('')
  const [busyId, setBusyId] = useState(null)

  async function handleCreate() {
    if (!newName.trim()) return
    setCreating(true)
    try {
      await createAndSwitch(newName.trim())
      setNewName('')
    } finally {
      setCreating(false)
    }
  }

  function handleSwitch(caseId) {
    setActiveCaseId(caseId)
    navigate('/')
  }

  function startRename(c) {
    setRenamingId(c.id)
    setRenameValue(c.name)
  }

  async function commitRename(caseId) {
    if (!renameValue.trim()) {
      setRenamingId(null)
      return
    }
    await renameCase(caseId, renameValue.trim())
    setRenamingId(null)
    await refreshCases()
  }

  async function handleDelete(c) {
    const isActive = c.id === activeCaseId
    if (
      !confirm(
        `Delete case "${c.name}"? This permanently removes its ${c.document_count} document(s) and ${c.check_count} logged check(s). This cannot be undone.`,
      )
    ) {
      return
    }
    setBusyId(c.id)
    try {
      await deleteCase(c.id)
      const remaining = await refreshCases()
      if (isActive) {
        setActiveCaseId(remaining[0]?.id || null)
      }
    } finally {
      setBusyId(null)
    }
  }

  return (
    <main className="page-single">
      <div className="page-header">
        <h2>Case Files</h2>
        <p className="muted page-intro">
          Each case is a fully separate project — its own corpus, its own search index, its own Case
          Log. Switch between them any time from the header, or manage them here.
        </p>
      </div>

      {error && <div className="banner-error">Can't reach the backend. Is the FastAPI server running?</div>}

      <div className="case-create-row">
        <input
          className="title-input"
          placeholder="New case name (e.g. Q3 Investor Report)"
          value={newName}
          onChange={(e) => setNewName(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && handleCreate()}
          disabled={creating}
        />
        <button onClick={handleCreate} disabled={creating || !newName.trim()}>
          {creating ? 'Creating…' : 'New Case'}
        </button>
      </div>

      {loading ? (
        <p className="muted" style={{ marginTop: 20 }}>
          Loading cases…
        </p>
      ) : cases.length === 0 ? (
        <p className="muted" style={{ marginTop: 20 }}>
          No cases yet — create your first one above.
        </p>
      ) : (
        <div className="case-grid">
          {cases.map((c) => {
            const isActive = c.id === activeCaseId
            return (
              <div className={`case-card${isActive ? ' case-card-active' : ''}`} key={c.id}>
                {isActive && <div className="case-card-badge">Active</div>}
                {renamingId === c.id ? (
                  <input
                    className="title-input"
                    value={renameValue}
                    autoFocus
                    onChange={(e) => setRenameValue(e.target.value)}
                    onKeyDown={(e) => e.key === 'Enter' && commitRename(c.id)}
                    onBlur={() => commitRename(c.id)}
                  />
                ) : (
                  <div className="case-card-title">{c.name}</div>
                )}
                <div className="case-card-meta">
                  {c.document_count} doc{c.document_count === 1 ? '' : 's'} · {c.check_count} check
                  {c.check_count === 1 ? '' : 's'} · opened {new Date(c.created_at).toLocaleDateString()}
                </div>
                <div className="case-card-actions">
                  {!isActive && (
                    <button className="btn-secondary" onClick={() => handleSwitch(c.id)}>
                      Switch to this case
                    </button>
                  )}
                  <button className="btn-secondary" onClick={() => startRename(c)}>
                    Rename
                  </button>
                  <button className="btn-danger" onClick={() => handleDelete(c)} disabled={busyId === c.id}>
                    {busyId === c.id ? 'Deleting…' : 'Delete'}
                  </button>
                </div>
              </div>
            )
          })}
        </div>
      )}
    </main>
  )
}
