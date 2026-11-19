import { useRef, useState } from 'react'

export default function CorpusUpload({ onIngest, status }) {
  const [title, setTitle] = useState('')
  const [text, setText] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const [uploadProgress, setUploadProgress] = useState(null) // e.g. "2 / 5 files"
  const fileInputRef = useRef(null)

  async function handleAdd() {
    if (!title.trim() || !text.trim()) return
    setBusy(true)
    setError(null)
    try {
      await onIngest([{ id: crypto.randomUUID(), title: title.trim(), text: text.trim() }])
      setTitle('')
      setText('')
    } catch (err) {
      setError(err?.response?.data?.detail || err?.message || 'Upload failed. Is the backend running?')
    } finally {
      setBusy(false)
    }
  }

  async function handleFiles(e) {
    const files = Array.from(e.target.files || [])
    if (!files.length) return

    setBusy(true)
    setError(null)
    setUploadProgress(`Reading 0 / ${files.length} file(s)…`)

    try {
      const docs = []
      for (let i = 0; i < files.length; i++) {
        const f = files[i]
        setUploadProgress(`Reading ${i + 1} / ${files.length}: ${f.name}`)
        const text = await readFileAsText(f)
        if (text.trim().length < 10) continue // skip empty / binary
        docs.push({ id: crypto.randomUUID(), title: f.name, text })
      }

      if (!docs.length) {
        setError('No readable text found in the selected file(s).')
        return
      }

      setUploadProgress(`Indexing ${docs.length} document(s)…`)
      await onIngest(docs)
      setUploadProgress(null)
    } catch (err) {
      setError(err?.response?.data?.detail || err?.message || 'Upload failed. Is the backend running?')
      setUploadProgress(null)
    } finally {
      setBusy(false)
      // Reset the input so the same file can be re-uploaded if needed
      if (fileInputRef.current) fileInputRef.current.value = ''
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

      {error && (
        <div className="banner-error" style={{ marginBottom: 8 }}>
          ⚠ {error}
        </div>
      )}

      {uploadProgress && (
        <div className="banner-info" style={{ marginBottom: 8 }}>
          ⏳ {uploadProgress}
        </div>
      )}

      <label className={`file-upload${busy ? ' disabled' : ''}`}>
        {busy ? uploadProgress || 'Uploading…' : 'Upload .txt / .md / .pdf files'}
        <input
          ref={fileInputRef}
          type="file"
          accept=".txt,.md,.pdf"
          multiple
          onChange={handleFiles}
          disabled={busy}
        />
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

/** Read a File as plain text. Handles UTF-8/latin-1 text files and
 *  does a best-effort extraction from PDF (reads raw text stream). */
function readFileAsText(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    if (file.name.toLowerCase().endsWith('.pdf')) {
      // For PDFs, read as ArrayBuffer and extract visible ASCII text
      reader.onload = () => {
        try {
          const bytes = new Uint8Array(reader.result)
          // Pull printable ASCII runs ≥ 4 chars out of the raw PDF bytes
          let text = ''
          let run = ''
          for (let i = 0; i < bytes.length; i++) {
            const c = bytes[i]
            if (c >= 32 && c < 127) {
              run += String.fromCharCode(c)
            } else {
              if (run.length >= 4) text += run + ' '
              run = ''
            }
          }
          if (run.length >= 4) text += run
          resolve(text.trim())
        } catch (err) {
          reject(err)
        }
      }
      reader.onerror = reject
      reader.readAsArrayBuffer(file)
    } else {
      reader.onload = () => resolve(String(reader.result))
      reader.onerror = reject
      reader.readAsText(file)
    }
  })
}
