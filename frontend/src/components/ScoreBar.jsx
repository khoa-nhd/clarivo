export default function ScoreBar({ label, value }) {
  const safeValue = Math.max(0, Math.min(100, Number(value) || 0))
  return (
    <div className="score-row">
      <div className="score-label"><span>{label}</span><strong>{safeValue}</strong></div>
      <div className="score-track"><span style={{ width: `${safeValue}%` }} /></div>
    </div>
  )
}
