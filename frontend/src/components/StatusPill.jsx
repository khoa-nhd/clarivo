const labels = {
  queued: 'Queued',
  processing: 'Analyzing',
  complete: 'Complete',
  error: 'Needs retry',
}

export default function StatusPill({ status }) {
  return (
    <span className={`status-pill status-${status}`}>
      <span className="status-dot" />
      {labels[status] || status}
    </span>
  )
}
