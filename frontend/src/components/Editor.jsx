import { useEffect, useMemo, useRef, useState } from 'react'
import { splitSentences } from '../sentences.js'
import { checkClaim } from '../api.js'

const DEBOUNCE_MS = 700

export default function Editor({ text, setText, cache, setCache, onOpenEvidence, corpusReady, caseId }) {
  const [inFlight, setInFlight] = useState(new Set())
  const timerRef = useRef(null)

  const sentences = useMemo(() => splitSentences(text), [text])

  useEffect(() => {
    if (!corpusReady) return
    clearTimeout(timerRef.current)
    timerRef.current = setTimeout(() => {
      const complete = sentences.filter((s) => s.complete && s.text.length > 3)
      complete.forEach((s, idx) => {
        if (cache[s.text] || inFlight.has(s.text)) return
        const context = idx > 0 ? complete[idx - 1].text : null
        runCheck(s.text, context)
      })
    }, DEBOUNCE_MS)
    return () => clearTimeout(timerRef.current)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [text, corpusReady, caseId])

  async function runCheck(sentenceText, context) {
    setInFlight((prev) => new Set(prev).add(sentenceText))
    try {
      const result = await checkClaim(caseId, sentenceText, context)
      setCache((prev) => ({ ...prev, [sentenceText]: result }))
    } catch (err) {
      setCache((prev) => ({
        ...prev,
        [sentenceText]: {
          sentence: sentenceText,
          verdict: 'unverified',
          explanation: 'Could not reach the checking service.',
          best_evidence: null,
          evidence: [],
        },
      }))
    } finally {
      setInFlight((prev) => {
        const next = new Set(prev)
        next.delete(sentenceText)
        return next
      })
    }
  }

  return (
    <div className="editor-panel">
      <h2>Draft</h2>
      <textarea
        className="draft-textarea"
        placeholder="Start writing... completed sentences are checked against your corpus automatically."
        value={text}
        onChange={(e) => setText(e.target.value)}
        disabled={!corpusReady}
      />

      <h3 className="preview-label">Live preview</h3>
      <div className="preview">
        {sentences.length === 0 && <span className="muted">Your highlighted draft will appear here as you type.</span>}
        {sentences.map((s, i) => {
          const result = cache[s.text]
          const checking = s.complete && inFlight.has(s.text)
          let cls = 'sentence-span'
          if (!s.complete) cls += ' pending-input'
          else if (checking) cls += ' checking'
          else if (result) cls += ` verdict-${result.verdict}`
          else cls += ' queued'

          return (
            <span
              key={`${i}-${s.text.slice(0, 12)}`}
              className={cls}
              onClick={() => result && onOpenEvidence({ text: s.text, result })}
              title={result ? result.verdict : s.complete ? 'checking…' : 'still typing…'}
            >
              {s.text}
              {result && (
                <span className={`sentence-mark verdict-${result.verdict}`}>
                  {result.verdict === 'supported' && '✓'}
                  {result.verdict === 'contradicted' && '✕'}
                  {result.verdict === 'unverified' && '—'}
                </span>
              )}{' '}
            </span>
          )
        })}
      </div>

      {!corpusReady && <p className="muted warn">Add at least one document to the corpus to start checking claims.</p>}
    </div>
  )
}
