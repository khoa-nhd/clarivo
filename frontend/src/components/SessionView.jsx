import StatusPill from './StatusPill.jsx'
import ReportView from './ReportView.jsx'
import TranscriptCard from './TranscriptCard.jsx'
import InteractiveDrill from './InteractiveDrill.jsx'

function formatDate(iso) {
  return new Date(iso).toLocaleString([], {
    month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit',
  })
}

function moduleLabel(name, state, fallbackReady = false) {
  if (state === 'complete') return `${name} scored`
  if (state === 'processing') return `${name} analyzing`
  if (state === 'error') return `${name} unavailable`
  if (state === 'unavailable') return `${name} unavailable`
  if (fallbackReady) return `${name} ready`
  return name
}

//: Delivery states that leave something worth re-running - but only for a
//: capability the session actually recorded. An audio-only session reports
//: vision "unavailable" forever and quite correctly, and treating that as
//: unfinished work left the offer on screen with nothing to do.
const DELIVERY_INCOMPLETE = ['unavailable', 'error']
const DELIVERY_RUNNING = ['processing', 'queued']

export default function SessionView({ session, onNew, onRetry, onRetryDelivery, onDelete, onUpdateTranscript, onAnswerDrill, onRegenerateDrills, onFinalizeDrills }) {
  const states = session.analysisState || {}
  const contentDone = Boolean(session.result) || states.content === 'complete'
  const voiceDone = Boolean(session.delivery?.voice) || states.audio === 'complete'
  const visualDone = Boolean(session.delivery?.visual) || states.vision === 'complete'

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
          <span className={`module-mini ${contentDone ? 'active' : ''}`}>{moduleLabel('Content', states.content, Boolean(session.transcript))}</span>
          <span className={`module-mini ${voiceDone ? 'audio-captured' : ''}`}>{moduleLabel('Voice', states.audio, Boolean(session.audio))}</span>
          <span className={`module-mini ${visualDone ? 'audio-captured' : ''}`}>{moduleLabel('Visual', states.vision, Boolean(session.video))}</span>
        </div>
      </section>

      {session.topicProfile && (
        <section className="session-topic-brief">
          <div><span>Domain</span><strong>{session.topicProfile.domain}</strong></div>
          <div><span>Difficulty</span><strong>{session.topicProfile.difficulty}</strong></div>
          <div className="session-topic-brief-wide"><span>Practice task</span><strong>{session.topicProfile.taskDescription}</strong></div>
          <div className="session-keywords">{(session.topicProfile.preStudyKeywords || []).map((keyword) => <span key={keyword}>{keyword}</span>)}</div>
        </section>
      )}

      {['preparing', 'queued'].includes(session.status) && (
        <section className="state-card queued-state">
          <div className="state-visual"><span>1</span><i /><i /><i /></div>
          <div>
            <div className="eyebrow">Queued</div>
            <h2>Waiting to analyze</h2>
            
          </div>
        </section>
      )}

      {session.status === 'processing' && (
        <section className="state-card processing-state">
          <div className="loader-orbit"><span /></div>
          <div>
            <div className="eyebrow">Analyzing</div>
            <h2>Reviewing your presentation</h2>
            
            <div className="analysis-progress"><span /></div>
          </div>
        </section>
      )}

      {session.status === 'error' && (
        <section className="state-card error-state">
          <div className="error-mark">!</div>
          <div>
            <div className="eyebrow">Analysis failed</div>
            <h2>Analysis failed</h2>
            <p>{session.error}</p>
            <button className="primary-button compact-button" onClick={() => onRetry(session.id)}>Retry analysis</button>
          </div>
        </section>
      )}

      {/* A session whose content report succeeded completes even when voice or
          visual did not, so the "Analysis failed" retry above never appears for
          it. Without this there is nothing to click: the recording is still in
          the browser, the backend may since have recovered, and re-running the
          whole session would spend another content analysis and throw away the
          Q&A progress. */}
      {session.status === 'complete'
        && ((session.audio && DELIVERY_INCOMPLETE.includes(session.analysisState?.audio))
          || (session.video && DELIVERY_INCOMPLETE.includes(session.analysisState?.vision)))
        && (
        <section className="state-card delivery-retry-state">
          <div>
            <div className="eyebrow">Delivery analysis incomplete</div>
            <p>
              {session.deliveryError
                || 'Voice or visual analysis did not run for this session. The recording is still here, so it can be scored without redoing the content report.'}
            </p>
            <button
              className="primary-button compact-button"
              onClick={() => onRetryDelivery(session.id)}
              disabled={DELIVERY_RUNNING.includes(session.analysisState?.audio)
                || DELIVERY_RUNNING.includes(session.analysisState?.vision)}
            >
              Re-run voice &amp; visual
            </button>
          </div>
        </section>
      )}

      {session.status === 'complete' && (
        <>
          <ReportView result={session.result} delivery={session.delivery} deliveryError={session.deliveryError} />
          <InteractiveDrill
            session={session}
            onAnswer={onAnswerDrill}
            onRegenerate={onRegenerateDrills}
            onFinalize={onFinalizeDrills}
          />
        </>
      )}

      <TranscriptCard session={session} onUpdateTranscript={onUpdateTranscript} />
    </main>
  )
}
