import { useMemo, useState } from 'react'
import VoiceTranscriptRecorder from './VoiceTranscriptRecorder.jsx'

const audiences = [
  'Beginner',
  'Intermediate',
  'Advanced',
  'Expert',
]

export default function NewSessionForm({ onSubmit, queueCount }) {
  const [topic, setTopic] = useState('')
  const [targetAudience, setTargetAudience] = useState('Beginner')
  const [transcript, setTranscript] = useState('')
  const [referenceContent, setReferenceContent] = useState('')
  const [showReference, setShowReference] = useState(false)
  const [isRecording, setIsRecording] = useState(false)
  const [isTranscribing, setIsTranscribing] = useState(false)
  const [audioDraft, setAudioDraft] = useState(null)
  const [recorderResetKey, setRecorderResetKey] = useState(0)

  const wordCount = useMemo(() => {
    const value = transcript.trim()
    return value ? value.split(/\s+/).length : 0
  }, [transcript])

  const busy = isRecording || isTranscribing
  const canSubmit = !busy && topic.trim().length >= 2 && transcript.trim().length >= 20

  function submit(event) {
    event.preventDefault()
    if (!canSubmit) return

    onSubmit({
      topic,
      targetAudience,
      transcript,
      referenceContent,
      audioBlob: audioDraft?.blob || null,
      audioMeta: audioDraft
        ? {
            durationSeconds: audioDraft.durationSeconds,
            mimeType: audioDraft.mimeType,
            sizeBytes: audioDraft.sizeBytes,
            transcriptionModel: audioDraft.transcriptionModel,
            transcriptionWordCount: audioDraft.transcriptionWordCount,
            language: 'en',
          }
        : null,
    })

    setTopic('')
    setTranscript('')
    setReferenceContent('')
    setShowReference(false)
    setAudioDraft(null)
    setRecorderResetKey((value) => value + 1)
  }

  return (
    <main className="workspace-main new-session-page">
      <section className="hero-card">
        <div className="hero-copy">
          <div className="mode-badge"><span /> Transcript feedback MVP</div>
          <h1>Explain it. <em>Understand it.</em></h1>
          <p>
            Record your explanation in English or paste a transcript. Review the transcript first, then Clarivo checks correctness,
            clarity, completeness, logical flow, examples, and audience fit while your other sessions keep processing.
          </p>
        </div>
        <div className="future-strip">
          <div className="future-step active"><span>01</span><strong>Content</strong><small>Available now</small></div>
          <div className="future-line" />
          <div className={`future-step ${audioDraft ? 'captured' : ''}`}><span>02</span><strong>Delivery</strong><small>{audioDraft ? 'Audio captured' : 'Analysis later'}</small></div>
          <div className="future-line" />
          <div className="future-step"><span>03</span><strong>Visual</strong><small>CV reserved</small></div>
        </div>
      </section>

      <form className="session-form" onSubmit={submit}>
        <div className="form-heading">
          <div>
            <div className="eyebrow">New practice</div>
            <h2>Record, review, then analyze</h2>
          </div>
          {queueCount > 0 && <span className="queue-live">{queueCount} waiting</span>}
        </div>

        <div className="form-grid">
          <label className="field">
            <span>Topic</span>
            <input
              value={topic}
              onChange={(event) => setTopic(event.target.value)}
              placeholder="e.g. Why least squares uses squared errors"
              autoFocus
            />
          </label>

          <label className="field">
            <span>Target audience</span>
            <select value={targetAudience} onChange={(event) => setTargetAudience(event.target.value)}>
              {audiences.map((audience) => <option key={audience}>{audience}</option>)}
            </select>
          </label>
        </div>

        <VoiceTranscriptRecorder
          key={recorderResetKey}
          resetKey={recorderResetKey}
          topic={topic}
          setTranscript={setTranscript}
          onRecordingChange={setIsRecording}
          onTranscribingChange={setIsTranscribing}
          onAudioReady={setAudioDraft}
        />

        <label className="field transcript-field">
          <div className="field-row">
            <span>Your transcript</span>
            <small>{wordCount} words</small>
          </div>
          <textarea
            value={transcript}
            onChange={(event) => setTranscript(event.target.value)}
            placeholder="After you stop recording, Whisper will put the English transcript here. Review and correct any recognition mistakes before submitting, or paste/type a transcript manually."
            disabled={busy}
          />
        </label>

        {audioDraft && !busy && (
          <div className="audio-ready-note">
            <span>✓</span>
            <div>
              <strong>Recording attached to this draft</strong>
              <p>The raw audio will be stored locally with the session. Later, the Delivery module can reuse this exact recording for pace, pauses, filler words, volume, and other speech metrics.</p>
            </div>
          </div>
        )}

        <div className="optional-block">
          <button type="button" className="text-button" onClick={() => setShowReference((value) => !value)}>
            {showReference ? '− Hide' : '+ Add'} optional reference content
          </button>
          {showReference && (
            <label className="field compact-field">
              <span>Reference notes / expected content</span>
              <textarea
                className="compact-textarea"
                value={referenceContent}
                onChange={(event) => setReferenceContent(event.target.value)}
                placeholder="Optional. You can leave this blank and let the model evaluate from the topic."
              />
            </label>
          )}
        </div>

        <div className="form-footer">
          <div className="form-hint">
            <span className="hint-dot" />
            Review and edit the transcript first. After you submit, the session enters the queue and you can immediately create another one.
          </div>
          <button className="primary-button" disabled={!canSubmit}>
            {isRecording
              ? 'Stop recording before submitting'
              : isTranscribing
                ? 'Wait for transcription'
                : 'Add to analysis queue'} <span>→</span>
          </button>
        </div>
      </form>
    </main>
  )
}
