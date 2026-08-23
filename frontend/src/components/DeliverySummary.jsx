function numeric(value) {
  if (value === null || value === undefined || value === '') return null
  const number = Number(value)
  return Number.isFinite(number) ? number : null
}

function round(value) {
  const number = numeric(value)
  return number === null ? null : Math.round(number)
}

function oneDecimal(value) {
  const number = numeric(value)
  return number === null ? null : Math.round(number * 10) / 10
}

function percent(value) {
  const number = numeric(value)
  return number === null ? '—' : `${Math.round(number)}%`
}

function seconds(value) {
  const number = numeric(value)
  return number === null ? '—' : `${Math.round(number)}s`
}

function scoreWord(value) {
  const number = round(value)
  if (number === null) return 'Not available'
  if (number >= 90) return 'Excellent'
  if (number >= 80) return 'Strong'
  if (number >= 70) return 'Good'
  if (number >= 55) return 'Mixed'
  return 'Needs work'
}

function voicePaceLabel(wpm) {
  const number = numeric(wpm)
  if (number === null) return 'Not available'
  if (number < 105) return 'Too slow'
  if (number < 165) return 'Comfortable'
  if (number < 180) return 'A bit fast'
  return 'Too fast'
}

function gestureLabel(level, reliable) {
  if (reliable === false) return 'Low visibility'
  if (!level) return 'Not available'
  const map = {
    'NO CLEAR GESTURES': 'Minimal gestures',
    GESTURING: 'Purposeful gestures',
    'FREQUENT GESTURES': 'Frequent gestures',
    'LITTLE MOVEMENT': 'Little movement',
    'SOME MOVEMENT': 'Some movement',
    'FREQUENT MOVEMENT': 'Frequent movement',
  }
  return map[level] || level
}

function BarMetric({ label, score, meta, tone = 'default' }) {
  const scoreValue = round(score)
  const pct = Math.max(0, Math.min(100, scoreValue ?? 0))
  return (
    <div className={`delivery-bar-card tone-${tone} ${scoreValue === null ? 'metric-unavailable' : ''}`}>
      <div className="delivery-bar-top">
        <span>{label}</span>
        <strong>{scoreValue ?? '—'}</strong>
      </div>
      <div className="delivery-bar-track"><span style={{ width: `${pct}%` }} /></div>
      {meta && <small>{meta}</small>}
    </div>
  )
}

function StatPill({ label, value, note, warn = false }) {
  return (
    <div className={`delivery-stat-pill ${warn ? 'warn' : ''}`}>
      <span>{label}</span>
      <strong>{value}</strong>
      {note ? <small>{note}</small> : null}
    </div>
  )
}

function FeedbackList({ title, items }) {
  if (!Array.isArray(items) || !items.length) return null
  return (
    <div className="delivery-feedback-box">
      <div className="delivery-feedback-title">{title}</div>
      <ul>
        {items.map((item, index) => <li key={`${title}-${index}`}>{item}</li>)}
      </ul>
    </div>
  )
}

function OverviewChip({ label, value, accent = false }) {
  return (
    <div className={`delivery-overview-chip ${accent ? 'accent' : ''}`}>
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  )
}

function SignalFlag({ active, children, tone = 'warning' }) {
  if (!active) return null
  return <span className={`delivery-signal-flag ${tone}`}>{children}</span>
}

export default function DeliverySummary({ delivery, error }) {
  if (!delivery) {
    if (!error) return null
    return (
      <section className="delivery-unavailable">
        <div>
          <div className="eyebrow">Delivery analysis</div>
          <h2>Content feedback is ready.</h2>
          <p>{error}</p>
        </div>
      </section>
    )
  }

  const voice = delivery.voice || {}
  const visual = delivery.visual || {}
  const voiceScore = round(delivery.voice_score)
  const visualScore = round(delivery.visual_score)
  const availableScores = [voiceScore, visualScore].filter((value) => value !== null)
  const overallScore = availableScores.length
    ? Math.round(availableScores.reduce((sum, value) => sum + value, 0) / availableScores.length)
    : null

  const priorities = Array.isArray(delivery.top_priorities) ? delivery.top_priorities.slice(0, 4) : []
  const fillerReliable = (numeric(voice.filler_reliability) ?? 0) >= 70
  const noSpeech = Boolean(voice.no_speech_detected) || voice.speech_state === 'NO_SPEECH_DETECTED'
  const transcriptFillers = round(voice.filler_count_transcript) ?? 0
  const acousticFillers = round(voice.implicit_filler_count) ?? 0
  const totalFillers = round(voice.filler_count) ?? 0

  const voiceHighlights = [
    noSpeech ? 'No clear speech detected' : voice.wpm ? `Pace ${round(voice.wpm)} WPM` : null,
    numeric(voice.speech_snr_db) !== null ? `SNR ${oneDecimal(voice.speech_snr_db)} dB` : null,
    fillerReliable ? `${totalFillers} fillers (${acousticFillers} acoustic)` : 'Filler confidence limited',
  ].filter(Boolean)

  const visualHighlights = [
    numeric(visual.visible_forward_percent) !== null ? `${percent(visual.visible_forward_percent)} centered while visible` : null,
    numeric(visual.pose_backed_presence_percent) !== null ? `${percent(visual.pose_backed_presence_percent)} pose-backed presence` : null,
    gestureLabel(visual.gesture_level, visual.gesture_reliable),
  ].filter(Boolean)

  return (
    <section className="delivery-summary-card rich-delivery-card">
      <div className="delivery-summary-heading rich-delivery-heading">
        <div>
          <div className="eyebrow">Presentation delivery</div>
          <h2>Voice & visual</h2>
          
        </div>

      </div>

      {noSpeech && (
        <div className="delivery-status-alert">
          <strong>No reliable speech detected.</strong>
          
        </div>
      )}

      <div className="delivery-overview-grid">
        <div className="delivery-overview-main">
          <div className="delivery-overview-score">
            <span>Overall delivery</span>
            <strong>{overallScore ?? '—'}</strong>
            <small>{scoreWord(overallScore)}</small>
          </div>
          <div className="delivery-overview-details">
            <OverviewChip label="Voice" value={voiceScore ?? '—'} accent />
            <OverviewChip label="Visual" value={visualScore ?? '—'} accent />
          </div>
        </div>

        <div className="delivery-highlights-card">
          <div className="delivery-highlights-section">
            <span className="delivery-panel-tag">Voice highlights</span>
            <div className="delivery-highlight-list">
              {voiceHighlights.map((item, index) => <div className="delivery-highlight" key={`voice-${index}`}>{item}</div>)}
            </div>
          </div>
          <div className="delivery-highlights-section">
            <span className="delivery-panel-tag">Visual highlights</span>
            <div className="delivery-highlight-list">
              {visualHighlights.map((item, index) => <div className="delivery-highlight" key={`visual-${index}`}>{item}</div>)}
            </div>
          </div>
        </div>
      </div>

      <div className="delivery-deep-grid">
        <article className="delivery-panel voice-panel">
          <div className="delivery-panel-header">
            <div>
              <span className="delivery-panel-tag">Voice delivery</span>
              <h3>{scoreWord(voiceScore)}</h3>
              
            </div>
            <div className="delivery-panel-score voice">{voiceScore ?? '—'}</div>
          </div>

          {!noSpeech && (
            <div className="delivery-bar-grid">
              <BarMetric label="Pace" score={voice.pace_score} meta={voice.wpm ? `${round(voice.wpm)} WPM · ${voicePaceLabel(voice.wpm)}` : 'Pace unavailable'} tone="voice" />
              <BarMetric label="Pause control" score={voice.pause_score} meta={numeric(voice.long_pause_count) !== null ? `${round(voice.long_pause_count)} long pauses · longest ${seconds(voice.longest_pause_seconds)}` : 'Pause timing unavailable'} tone="voice" />
              <BarMetric label="Audibility" score={voice.audibility_score} meta={numeric(voice.speech_snr_db) !== null ? `${oneDecimal(voice.speech_snr_db)} dB speech-to-noise` : 'Signal quality unavailable'} tone="voice" />
              <BarMetric label="Fluency" score={voice.fluency_score} meta="Pauses + fillers" tone="voice" />
              <BarMetric label="Volume stability" score={voice.volume_stability_score} meta="Voice level consistency" tone="voice" />
              <BarMetric label="Pace stability" score={voice.pace_stability_score} meta="Speaking rhythm" tone="voice" />
              {fillerReliable && <BarMetric label="Filler control" score={voice.filler_score} meta={`${totalFillers} total · ${transcriptFillers} transcript · ${acousticFillers} prolonged-vowel`} tone="voice" />}
            </div>
          )}

          <div className="delivery-stat-grid">
            <StatPill label="Voice activity" value={numeric(voice.voice_activity_ratio) !== null ? percent(numeric(voice.voice_activity_ratio) * 100) : '—'} note="Speech / recording" warn={Boolean(voice.abnormal_dead_silence)} />
            <StatPill label="Speaking time" value={seconds(voice.speaking_time_seconds)} note={voice.duration_seconds ? `${seconds(voice.duration_seconds)} recording` : null} />
            <StatPill label="Articulation pace" value={voice.articulation_wpm ? `${round(voice.articulation_wpm)} WPM` : '—'} note="While speaking" />
            <StatPill label="Average pause" value={voice.average_pause_seconds ? `${oneDecimal(voice.average_pause_seconds)}s` : '—'} note={voice.pause_time_seconds ? `${seconds(voice.pause_time_seconds)} total pause time` : null} />
            <StatPill label="Filler detection" value={fillerReliable ? `${totalFillers}` : 'Low confidence'} note={fillerReliable ? `${transcriptFillers} spoken + ${acousticFillers} acoustic` : 'Low confidence'} />
            
          </div>

          <div className="delivery-signal-row">
            <SignalFlag active={voice.abnormal_dead_silence}>Long silence detected</SignalFlag>
            <SignalFlag active={acousticFillers > 0} tone="info">Acoustic hesitation detected</SignalFlag>
          </div>

          <FeedbackList title="Voice coaching notes" items={voice.feedback} />
        </article>

        <article className="delivery-panel visual-panel">
          <div className="delivery-panel-header">
            <div>
              <span className="delivery-panel-tag">Visual delivery</span>
              <h3>{scoreWord(visualScore)}</h3>
              
            </div>
            <div className="delivery-panel-score visual">{visualScore ?? '—'}</div>
          </div>

          <div className="delivery-bar-grid">
            <BarMetric label="Camera attention" score={visual.attention_score} meta={numeric(visual.visible_forward_percent) !== null ? `${percent(visual.visible_forward_percent)} centered while visible` : 'Attention unavailable'} tone="visual" />
            <BarMetric label="Head stability" score={visual.head_stability_score} meta={numeric(visual.head_motion_p75_deg) !== null ? `Head movement ${oneDecimal(visual.head_motion_p75_deg)}°` : 'Movement unavailable'} tone="visual" />
            <BarMetric label="Presence" score={visual.presence_score} meta={numeric(visual.pose_backed_presence_percent) !== null ? `${percent(visual.pose_backed_presence_percent)} in frame` : 'Presence unavailable'} tone="visual" />
            {visual.posture_score != null && <BarMetric label="Posture" score={visual.posture_score} meta={numeric(visual.posture_good_percent) !== null ? `${percent(visual.posture_good_percent)} good posture frames` : 'Posture unavailable'} tone="visual" />}
          </div>

          <div className="delivery-stat-grid">
            <StatPill label="Looking-away events" value={round(visual.looking_away_episode_count) ?? '—'} note={visual.sustained_looking_away_seconds ? `${seconds(visual.sustained_looking_away_seconds)} sustained look-away` : 'No sustained look-away'} warn={Boolean(visual.gaze_repeat_triggered)} />
            <StatPill label="Direct attention" value={percent(visual.direct_forward_percent)} note="Very centered moments" />
            <StatPill label="Tracking stability" value={percent(visual.held_orientation_percent)} note="Stable tracking" />
            <StatPill label="Posture quality" value={visual.posture_score != null ? percent(visual.posture_good_percent) : 'Low evidence'} note={visual.posture_score != null ? `${percent(visual.posture_bad_percent)} weak frames` : 'Need clearer shoulders/torso'} warn={Boolean(visual.posture_repeat_triggered)} />
            <StatPill label="Gesture activity" value={gestureLabel(visual.gesture_level, visual.gesture_reliable)} note={visual.gesture_reliable ? `${percent(visual.gesture_activity_percent)} active · ${round(visual.gesture_event_count) ?? 0} events` : 'Arms not visible enough'} />
            <StatPill label="Eye tracking" value={percent(visual.gaze_estimation_used_percent)} note="Eye-gaze frames" />
          </div>

          <div className="delivery-signal-row">
            <SignalFlag active={visual.gaze_repeat_triggered}>Repeated look-away pattern</SignalFlag>
            <SignalFlag active={visual.head_turn_repeat_triggered}>Repeated head turns</SignalFlag>
            <SignalFlag active={visual.posture_repeat_triggered}>Repeated posture deviations</SignalFlag>
            <SignalFlag active={visual.gesture_reliable === false} tone="info">Gesture visibility limited</SignalFlag>
          </div>

          <FeedbackList title="Visual coaching notes" items={visual.feedback} />
        </article>
      </div>

      {priorities.length > 0 && (
        <div className="delivery-priorities rich-priorities">
          <div className="delivery-priority-title">Delivery priorities</div>
          <div className="delivery-priority-grid">
            {priorities.map((priority, index) => (
              <div className="delivery-priority-card" key={`${priority}-${index}`}>
                <span>{String(index + 1).padStart(2, '0')}</span>
                <p>{priority}</p>
              </div>
            ))}
          </div>
        </div>
      )}

      {error ? <div className="delivery-side-error">Delivery issue: {error}</div> : null}
    </section>
  )
}
