export default function ScorePanel({ results }) {
  const checked = results.filter((r) => r.result && r.result.verdict)
  const total = checked.length
  const supported = checked.filter((r) => r.result.verdict === 'supported').length
  const contradicted = checked.filter((r) => r.result.verdict === 'contradicted').length
  const unverified = checked.filter((r) => r.result.verdict === 'unverified').length
  const pct = (n) => (total ? Math.round((n / total) * 100) : 0)

  let stampClass = 'stamp'
  if (total > 0) {
    if (contradicted > 0 && contradicted >= supported) stampClass += ' stamp-contradicted'
    else if (supported > 0) stampClass += ' stamp-supported'
  }

  return (
    <div className="score-panel">
      <h2>Verification Stamp</h2>

      <div className={stampClass}>
        <div className="stamp-value">{total ? `${pct(supported)}%` : '—'}</div>
        <div className="stamp-caption">Grounded</div>
      </div>

      <p className="muted">
        {total} claim{total === 1 ? '' : 's'} checked
      </p>

      <div className="score-bar">
        <div className="score-seg supported" style={{ width: `${pct(supported)}%` }} />
        <div className="score-seg contradicted" style={{ width: `${pct(contradicted)}%` }} />
        <div className="score-seg unverified" style={{ width: `${pct(unverified)}%` }} />
      </div>

      <ul className="score-legend">
        <li>
          <span className="dot supported" /> Supported — {supported}
        </li>
        <li>
          <span className="dot contradicted" /> Contradicted — {contradicted}
        </li>
        <li>
          <span className="dot unverified" /> Unverified — {unverified}
        </li>
      </ul>
    </div>
  )
}
