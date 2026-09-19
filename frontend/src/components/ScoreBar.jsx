import { useId, useState } from 'react'

const confidenceLabels = {
  high: 'High confidence',
  medium: 'Medium confidence',
  low: 'Low confidence',
  insufficient_evidence: 'Not enough evidence',
}

export default function ScoreBar({ label, value, evidence }) {
  const [open, setOpen] = useState(false)
  const panelId = useId()

  const safeValue = Math.max(0, Math.min(100, Number(value) || 0))
  const quotes = Array.isArray(evidence?.evidence) ? evidence.evidence.filter(Boolean) : []
  const reasoning = evidence?.reasoning?.trim() || ''
  const confidence = evidence?.confidence || ''
  const hasDetail = Boolean(quotes.length || reasoning || confidence)

  if (!hasDetail) {
    return (
      <div className="score-row">
        <div className="score-label"><span>{label}</span><strong>{safeValue}</strong></div>
        <div className="score-track"><span style={{ width: `${safeValue}%` }} /></div>
      </div>
    )
  }

  return (
    <div className="score-row">
      <button
        type="button"
        className="score-label score-label-button"
        onClick={() => setOpen((current) => !current)}
        aria-expanded={open}
        aria-controls={panelId}
      >
        <span>
          {label}
          <span className={`evidence-dot evidence-${confidence || 'unknown'}`} aria-hidden="true" />
        </span>
        <strong>{safeValue}</strong>
      </button>
      <div className="score-track"><span style={{ width: `${safeValue}%` }} /></div>
      {open && (
        <div className="score-evidence" id={panelId}>
          {confidence && (
            <span className={`evidence-confidence evidence-${confidence}`}>
              {confidenceLabels[confidence] || confidence}
            </span>
          )}
          {reasoning && <p className="evidence-reasoning">{reasoning}</p>}
          {quotes.length > 0 ? (
            <ul className="evidence-quotes">
              {quotes.map((quote, index) => <li key={index}>“{quote}”</li>)}
            </ul>
          ) : (
            confidence === 'insufficient_evidence' && (
              <p className="muted">
                The transcript did not contain enough material to judge this dimension confidently.
              </p>
            )
          )}
        </div>
      )}
    </div>
  )
}
