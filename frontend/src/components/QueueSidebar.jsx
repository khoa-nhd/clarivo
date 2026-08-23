import StatusPill from './StatusPill.jsx'

function relativeTime(iso) {
  if (!iso) return ''
  const delta = Date.now() - new Date(iso).getTime()
  const minutes = Math.max(0, Math.round(delta / 60000))
  if (minutes < 1) return 'just now'
  if (minutes < 60) return `${minutes}m ago`
  const hours = Math.round(minutes / 60)
  if (hours < 24) return `${hours}h ago`
  return new Date(iso).toLocaleDateString()
}

export default function QueueSidebar({ sessions, activeId, counts, onSelect, onDelete }) {
  function handleKeyDown(event, id) {
    if (event.key === 'Enter' || event.key === ' ') {
      event.preventDefault()
      onSelect(id)
    }
  }

  function deleteSession(event, session) {
    event.stopPropagation()
    if (session.status === 'processing') return
    if (window.confirm(`Delete “${session.topic}”?`)) onDelete(session.id)
  }

  return (
    <aside className="queue-panel">
      <div className="queue-header">
        <div>
          
          <h2>Sessions</h2>
        </div>
      </div>

      <div className="queue-summary">
        <div><strong>{counts.processing}</strong><span>active</span></div>
        <div><strong>{counts.queued}</strong><span>waiting</span></div>
        <div><strong>{counts.complete}</strong><span>done</span></div>
      </div>

      <div className="queue-list">
        {sessions.length === 0 ? (
          <div className="queue-empty">
            <div className="empty-orbit">◎</div>
            <p>No sessions yet.</p>
            
          </div>
        ) : sessions.map((session, index) => (
          <div
            className={`queue-card ${session.id === activeId ? 'active' : ''}`}
            key={session.id}
            onClick={() => onSelect(session.id)}
            onKeyDown={(event) => handleKeyDown(event, session.id)}
            role="button"
            tabIndex={0}
          >
            <div className="queue-card-top">
              <span className="queue-index">{String(sessions.length - index).padStart(2, '0')}</span>
              <div className="queue-card-actions">
                <StatusPill status={session.status} />
                <button
                  type="button"
                  className="queue-delete-button"
                  disabled={session.status === 'processing'}
                  onClick={(event) => deleteSession(event, session)}
                  aria-label={`Delete ${session.topic}`}
                  title={session.status === 'processing' ? 'Cannot delete while processing' : 'Delete session'}
                >
                  ×
                </button>
              </div>
            </div>
            <strong>{session.topic}</strong>
            <p>{session.targetAudience}</p>
            {session.drill?.rounds?.length > 0 && (
              <div className="queue-learning-progress">
                <span>Q&A {session.drill.rounds.length}/{session.drill.maxRounds || 3}</span>
                <span>{Math.round(session.drill.coreConceptsCoverage || 0)}% coverage</span>
              </div>
            )}
            <span className="queue-time">{relativeTime(session.createdAt)}</span>
          </div>
        ))}
      </div>


    </aside>
  )
}
