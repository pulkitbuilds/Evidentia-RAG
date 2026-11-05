import { useState } from 'react'

export default function CorpusUpload({ onIngest, status }) {
  const [title, setTitle] = useState('')
  const [text, setText] = useState('')
  const [busy, setBusy] = useState(false)

  async function handleAdd() {
    if (!title.trim() || !text.trim()) return
    setBusy(true)
    try {
      await onIngest([{ id: crypto.randomUUID(), title: title.trim(), text: text.trim() }])
      setTitle('')
      setText('')
    } finally {
      setBusy(false)
    }
  }

  async function handleFiles(e) {
    const files = Array.from(e.target.files || [])
    if (!files.length) return
    setBusy(true)
    try {
      const docs = await Promise.all(
        files.map(
          (f) =>
            new Promise((resolve, reject) => {
              const reader = new FileReader()
              reader.onload = () => resolve({ id: crypto.randomUUID(), title: f.name, text: String(reader.result) })
              reader.onerror = reject
              reader.readAsText(f)
            }),
        ),
      )
      await onIngest(docs)
    } finally {
      setBusy(false)
      e.target.value = ''
    }
  }

  return (
    <div className="corpus-panel">
      <h2>Source Corpus</h2>
      <p className="muted">
        {status.documents_indexed} document(s), {status.chunks_indexed} chunk(s) indexed.
      </p>
      {status.document_titles.length > 0 && (
        <ul className="doc-list">
          {status.document_titles.map((t) => (
            <li key={t}>{t}</li>
          ))}
        </ul>
      )}

      <label className="file-upload">
        Upload .txt / .md files
        <input type="file" accept=".txt,.md" multiple onChange={handleFiles} disabled={busy} />
      </label>

      <div className="divider">or paste text</div>

      <input
        className="title-input"
        placeholder="Source title (e.g. Q3 Report)"
        value={title}
        onChange={(e) => setTitle(e.target.value)}
        disabled={busy}
      />
      <textarea
        className="corpus-textarea"
        placeholder="Paste trusted source text here..."
        value={text}
        onChange={(e) => setText(e.target.value)}
        disabled={busy}
      />
      <button onClick={handleAdd} disabled={busy || !title.trim() || !text.trim()}>
        {busy ? 'Indexing...' : 'Add to corpus'}
      </button>
    </div>
  )
}
