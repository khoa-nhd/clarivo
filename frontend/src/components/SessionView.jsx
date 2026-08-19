import StatusPill from './StatusPill.jsx'
import ReportView from './ReportView.jsx'
import PlaceholderModule from './PlaceholderModule.jsx'
import TranscriptCard from './TranscriptCard.jsx'

function formatDate(iso) {
  return new Date(iso).toLocaleString([], {
    month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit',
  })
}

export default function SessionView({ session, onNew, onRetry, onDelete, onUpdateTranscript }) {
  return (
    <main className="workspace-main session-page">
      <div className="session-toolbar">
        <button className="back-button" onClick={onNew}>← New session</button>
        <div className="session-toolbar-actions">
          <StatusPill status={session.status} />
          <button
            className="ghost-button danger-on-hover"
            disabled={session.status === 'processing'}
            onClick={() => onDelete(session.id)}
          >
            Delete
          </button>
        </div>
      </div>

      <section className="session-title-block">
        <div>
          <div className="eyebrow">{session.targetAudience} · {formatDate(session.createdAt)}</div>
          <h1>{session.topic}</h1>
        </div>
        <div className="session-modules-mini">
          <span className="module-mini active">Content</span>
          <span className={`module-mini ${session.audio ? 'audio-captured' : ''}`}>{session.audio ? 'Audio captured' : 'Audio later'}</span>
          <span className="module-mini">Vision later</span>
        </div>
      </section>

      {session.status === 'queued' && (
        <section className="state-card queued-state">
          <div className="state-visual"><span>1</span><i /><i /><i /></div>
          <div>
            <div className="eyebrow">Waiting in queue</div>
            <h2>Your transcript is ready.</h2>
            <p>Another session is currently using the evaluator. You can create more sessions or inspect completed reports while this waits.</p>
          </div>
        </section>
      )}

      {session.status === 'processing' && (
        <section className="state-card processing-state">
          <div className="loader-orbit"><span /></div>
          <div>
            <div className="eyebrow">Qwen is analyzing</div>
            <h2>Checking the explanation.</h2>
            <p>Correctness → completeness → logical flow → clarity → examples → step continuity → audience fit.</p>
            <div className="analysis-progress"><span /></div>
          </div>
        </section>
      )}

      {session.status === 'error' && (
        <section className="state-card error-state">
          <div className="error-mark">!</div>
          <div>
            <div className="eyebrow">Analysis failed</div>
            <h2>This session needs another try.</h2>
            <p>{session.error}</p>
            <button className="primary-button compact-button" onClick={() => onRetry(session.id)}>Retry analysis</button>
          </div>
        </section>
      )}

      {session.status === 'complete' && <ReportView result={session.result} />}

      <TranscriptCard session={session} onUpdateTranscript={onUpdateTranscript} />

      <section className="future-modules compact-future">
        <PlaceholderModule
          eyebrow={session.audio ? "Recording ready" : "Reserved"}
          title="Delivery analysis"
          description={
            session.audio
              ? `The ${Math.round(session.audio.durationSeconds || 0)}s microphone recording is stored locally and ready for future pace, pauses, filler words, volume, and prosody analysis.`
              : "Record audio when creating a session and the same recording will be available for future delivery metrics."
          }
          icon="◉"
          pill={session.audio ? "Audio ready" : "Reserved"}
          ready={Boolean(session.audio)}
        />
        <PlaceholderModule
          eyebrow="Reserved"
          title="Visual communication"
          description="Computer-vision metrics will be attached to the same session object later."
          icon="◇"
        />
      </section>
    </main>
  )
}
