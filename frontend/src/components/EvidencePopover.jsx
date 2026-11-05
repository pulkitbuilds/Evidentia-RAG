const VERDICT_LABEL = {
  supported: 'Supported',
  contradicted: 'Contradicted',
  unverified: 'Unverified',
}

export default function EvidencePopover({ item, onClose }) {
  if (!item) return null
  const { verdict, explanation, best_evidence, evidence } = item.result || {}

  return (
    <div className="popover-backdrop" onClick={onClose}>
      <div className="popover" onClick={(e) => e.stopPropagation()}>
        <div className={`popover-header verdict-${verdict}`}>
          <span>{VERDICT_LABEL[verdict] || 'Checking…'}</span>
          <button className="close-btn" onClick={onClose}>×</button>
        </div>
        <p className="popover-sentence">&ldquo;{item.text}&rdquo;</p>
        {explanation && <p className="popover-explanation">{explanation}</p>}

        {best_evidence && (
          <div className="evidence-block">
            <div className="evidence-source">{best_evidence.doc_title}</div>
            <p className="evidence-text">{best_evidence.text}</p>
            <div className="evidence-scores">
              dense {best_evidence.dense_score.toFixed(2)} · sparse {best_evidence.sparse_score.toFixed(2)} · merged{' '}
              {best_evidence.merged_score.toFixed(2)}
            </div>
          </div>
        )}

        {evidence && evidence.length > 1 && (
          <details className="other-evidence">
            <summary>Other retrieved passages ({evidence.length - 1})</summary>
            {evidence.slice(1).map((e, i) => (
              <div className="evidence-block secondary" key={i}>
                <div className="evidence-source">{e.doc_title}</div>
                <p className="evidence-text">{e.text}</p>
              </div>
            ))}
          </details>
        )}

        {!best_evidence && verdict === 'unverified' && (
          <p className="muted">No relevant evidence was found in the corpus for this claim.</p>
        )}
      </div>
    </div>
  )
}
