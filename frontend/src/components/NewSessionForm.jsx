import { useMemo, useState } from 'react'
import TopicLibraryPicker from './TopicLibraryPicker.jsx'
import VoiceTranscriptRecorder from './VoiceTranscriptRecorder.jsx'
import VideoUploadPanel from './VideoUploadPanel.jsx'
import { topicLibrary } from '../data/topicLibrary.js'
import { refreshTopicLibrary } from '../services/api.js'

const audiences = ['Beginner', 'Intermediate', 'Advanced', 'Expert']
const TOPIC_LIBRARY_STORAGE = 'clarivo.topicLibrary.v2'

function loadTopicLibrary() {
  try {
    const saved = JSON.parse(localStorage.getItem(TOPIC_LIBRARY_STORAGE) || 'null')
    if (Array.isArray(saved) && saved.length >= 3) return saved
  } catch {}
  return topicLibrary
}

export default function NewSessionForm({ onSubmit, queueCount, visionEnabled = true }) {
  const [selectedProfile, setSelectedProfile] = useState(null)
  const [topic, setTopic] = useState('')
  const [targetAudience, setTargetAudience] = useState('Beginner')
  const [transcript, setTranscript] = useState('')
  const [referenceContent, setReferenceContent] = useState('')
  const [showReference, setShowReference] = useState(false)
  const [isRecording, setIsRecording] = useState(false)
  const [isTranscribing, setIsTranscribing] = useState(false)
  const [mediaDraft, setMediaDraft] = useState(null)
  const [recorderResetKey, setRecorderResetKey] = useState(0)
  const [mediaMode, setMediaMode] = useState('live')
  const [libraryTopics, setLibraryTopics] = useState(loadTopicLibrary)
  const [refreshingTopics, setRefreshingTopics] = useState(false)
  const [topicRefreshError, setTopicRefreshError] = useState('')

  const wordCount = useMemo(() => {
    const value = transcript.trim()
    return value ? value.split(/\s+/).length : 0
  }, [transcript])

  const busy = isRecording || isTranscribing
  const canSubmit = !busy && topic.trim().length >= 2 && transcript.trim().length >= 20

  function chooseProfile(profile) {
    setSelectedProfile(profile)
    setTopic(profile.title)
    setReferenceContent(profile.referenceContent)
    setTargetAudience(profile.recommendedAudience)
    setShowReference(false)
  }

  function chooseCustom() {
    setSelectedProfile({ id: 'custom' })
    setTopic('')
    setReferenceContent('')
    setTargetAudience('Beginner')
    setShowReference(false)
  }

  async function refreshTopics() {
    if (refreshingTopics) return
    setRefreshingTopics(true)
    setTopicRefreshError('')
    try {
      const fresh = await refreshTopicLibrary(libraryTopics, 5)
      if (!Array.isArray(fresh) || fresh.length < 3) throw new Error('Clarivo did not return enough new topics.')
      setLibraryTopics(fresh)
      localStorage.setItem(TOPIC_LIBRARY_STORAGE, JSON.stringify(fresh))
    } catch (error) {
      setTopicRefreshError(error?.message || 'Could not refresh topics. Your current library is still available.')
    } finally {
      setRefreshingTopics(false)
    }
  }

  function submit(event) {
    event.preventDefault()
    if (!canSubmit) return

    onSubmit({
      topic,
      targetAudience,
      transcript,
      referenceContent,
      topicProfile: selectedProfile?.id && selectedProfile.id !== 'custom'
        ? {
            id: selectedProfile.id,
            domain: selectedProfile.domain,
            difficulty: selectedProfile.difficulty,
            recommendedAudience: selectedProfile.recommendedAudience,
            taskDescription: selectedProfile.taskDescription,
            preStudyKeywords: selectedProfile.preStudyKeywords,
          }
        : null,
      audioBlob: mediaDraft?.audioBlob || null,
      videoBlob: mediaDraft?.videoBlob || null,
      audioMeta: mediaDraft
        ? {
            durationSeconds: mediaDraft.durationSeconds,
            mimeType: mediaDraft.audioMimeType,
            sizeBytes: mediaDraft.audioSizeBytes,
            transcriptionModel: mediaDraft.transcriptionModel,
            transcriptionWordCount: mediaDraft.transcriptionWordCount,
            rawTranscript: mediaDraft.rawTranscript || '',
            language: 'en',
          }
        : null,
      videoMeta: mediaDraft?.videoBlob
        ? {
            durationSeconds: mediaDraft.durationSeconds,
            mimeType: mediaDraft.videoMimeType,
            sizeBytes: mediaDraft.videoSizeBytes,
          }
        : null,
    })

    setSelectedProfile(null)
    setTopic('')
    setTargetAudience('Beginner')
    setTranscript('')
    setReferenceContent('')
    setShowReference(false)
    setMediaDraft(null)
    setRecorderResetKey((value) => value + 1)
  }

  return (
    <main className="workspace-main new-session-page">
      <section className="hero-card">
        <div className="hero-copy">
          
          <h1>Explain it. <em>Understand it.</em></h1>
          <p>Practice a topic, get feedback, then answer focused follow-up questions.</p>
        </div>
        <div className="future-strip">
          <div className="future-step active"><span>01</span><strong>Present</strong></div>
          <div className="future-line" />
          <div className="future-step"><span>02</span><strong>Q&A</strong></div>
          <div className="future-line" />
          <div className="future-step"><span>03</span><strong>Review</strong></div>
        </div>
      </section>

      <form className="session-form learning-session-form" onSubmit={submit}>
        <div className="form-heading">
          <div>
            <div className="eyebrow">New practice</div>
            <h2>Start a practice session</h2>
          </div>
          {queueCount > 0 && <span className="queue-live">{queueCount} waiting</span>}
        </div>

        <TopicLibraryPicker
          selectedId={selectedProfile?.id || ''}
          topics={libraryTopics}
          onSelect={chooseProfile}
          onCustom={chooseCustom}
          onRefresh={refreshTopics}
          refreshing={refreshingTopics}
          refreshError={topicRefreshError}
        />

        {selectedProfile?.id && selectedProfile.id !== 'custom' && (
          <section className="topic-profile-card">
            <div className="topic-profile-main">
              <div className="eyebrow">Practice task</div>
              <h3>{selectedProfile.title}</h3>
              <p>{selectedProfile.taskDescription}</p>
              <div className="study-keywords">
                {selectedProfile.preStudyKeywords.map((keyword) => <span key={keyword}>✓ {keyword}</span>)}
              </div>
            </div>
            <div className="topic-profile-side">
              <div><span>Difficulty</span><strong>{selectedProfile.difficulty}</strong></div>
              <div><span>Recommended audience</span><strong>{selectedProfile.recommendedAudience}</strong></div>
              
            </div>
          </section>
        )}

        <div className="form-grid topic-form-grid">
          <label className="field">
            <span>Topic</span>
            <input
              value={topic}
              onChange={(event) => {
                setTopic(event.target.value)
                if (selectedProfile?.id !== 'custom') setSelectedProfile({ id: 'custom' })
              }}
              placeholder="e.g. Why least squares uses squared errors"
            />
          </label>

          <label className="field">
            <span>Target audience</span>
            <select value={targetAudience} onChange={(event) => setTargetAudience(event.target.value)}>
              {audiences.map((audience) => <option key={audience}>{audience}</option>)}
            </select>
            {selectedProfile?.recommendedAudience && (
              <small className="audience-recommendation">Suggested: {selectedProfile.recommendedAudience}</small>
            )}
          </label>
        </div>

        <div className="media-mode-tabs" role="tablist" aria-label="Presentation input source">
          <button
            type="button"
            role="tab"
            aria-selected={mediaMode === 'live'}
            className={`media-mode-tab ${mediaMode === 'live' ? 'active' : ''}`}
            onClick={() => setMediaMode('live')}
            disabled={busy}
          >
            Record live
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={mediaMode === 'upload'}
            className={`media-mode-tab ${mediaMode === 'upload' ? 'active' : ''}`}
            onClick={() => setMediaMode('upload')}
            disabled={busy}
          >
            Upload a video
          </button>
        </div>

        {mediaMode === 'live' ? (
          <VoiceTranscriptRecorder
            key={`live-${recorderResetKey}`}
            resetKey={recorderResetKey}
            topic={topic}
            setTranscript={setTranscript}
            onRecordingChange={setIsRecording}
            onTranscribingChange={setIsTranscribing}
            onMediaReady={setMediaDraft}
          />
        ) : (
          <VideoUploadPanel
            key={`upload-${recorderResetKey}`}
            resetKey={recorderResetKey}
            topic={topic}
            setTranscript={setTranscript}
            onTranscribingChange={setIsTranscribing}
            onMediaReady={setMediaDraft}
            visionEnabled={visionEnabled}
          />
        )}

        <label className="field transcript-field">
          <div className="field-row">
            <span>Your transcript</span>
            <small>{wordCount} words</small>
          </div>
          <textarea
            value={transcript}
            onChange={(event) => setTranscript(event.target.value)}
            placeholder="Review or edit your transcript before analysis."
            disabled={busy}
          />
        </label>

        {mediaDraft && !busy && (
          <div className="audio-ready-note"><span>✓</span><div><strong>Recording ready</strong></div></div>
        )}

        {selectedProfile?.id === 'custom' && (
          <div className="optional-block">
            <button type="button" className="text-button" onClick={() => setShowReference((value) => !value)}>
              {showReference ? '− Hide' : '+ Add'} reference content
            </button>
            {showReference && (
              <label className="field compact-field">
                <span>Reference content</span>
                <textarea
                  className="compact-textarea"
                  value={referenceContent}
                  onChange={(event) => setReferenceContent(event.target.value)}
                  placeholder="Add key facts or expected content."
                />
              </label>
            )}
          </div>
        )}

        <div className="form-footer">
          <div className="form-hint">
            <span className="hint-dot" />
            Review your transcript before analysis.
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
