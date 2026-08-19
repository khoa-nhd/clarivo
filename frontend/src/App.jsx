import QueueSidebar from './components/QueueSidebar.jsx'
import NewSessionForm from './components/NewSessionForm.jsx'
import SessionView from './components/SessionView.jsx'
import { useSessionQueue } from './hooks/useSessionQueue.js'

export default function App() {
  const queue = useSessionQueue()

  return (
    <div className="app-shell">
      <header className="topbar">
        <button className="brand" onClick={queue.startNewSession} aria-label="Clarivo home">
          <span className="brand-mark">C</span>
          <span>Clarivo</span>
        </button>
        <div className="topbar-center">
          <span className="product-chip"><i /> Content + transcript ready</span>
        </div>
        <div className="topbar-right">
          <span className="version-chip">MVP · Record → transcript</span>
          <button className="new-top-button" onClick={queue.startNewSession}>+ New session</button>
        </div>
      </header>

      <div className="workspace-layout">
        {queue.activeSession ? (
          <SessionView
            session={queue.activeSession}
            onNew={queue.startNewSession}
            onRetry={queue.retrySession}
            onDelete={queue.removeSession}
            onUpdateTranscript={queue.updateTranscript}
          />
        ) : (
          <NewSessionForm
            onSubmit={queue.addSession}
            queueCount={queue.counts.queued + queue.counts.processing}
          />
        )}

        <QueueSidebar
          sessions={queue.sessions}
          activeId={queue.activeId}
          counts={queue.counts}
          onSelect={queue.setActiveId}
          onNew={queue.startNewSession}
          onDelete={queue.removeSession}
        />
      </div>
    </div>
  )
}
