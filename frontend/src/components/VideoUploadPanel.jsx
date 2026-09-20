import { useEffect, useRef, useState } from 'react'
import { HOSTED_UPLOAD_LIMIT_BYTES, localAiHasBodyCap, transcribeAudio } from '../services/api.js'
import { compressedAudioToWav } from '../services/audioProcessing.js'

// Fallbacks only. The real ceilings come from /api/health so the browser and
// the server cannot disagree - they already had, which is why an upload the
// server would have accepted was refused here at 80 MB.
const FALLBACK_MAX_RECORDING_SECONDS = 5 * 60
const FALLBACK_MAX_UPLOAD_VIDEO_BYTES = 1_024_000_000
const ACCEPTED_EXTENSIONS = /\.(mp4|webm|mov|m4v)$/i

function formatDuration(totalSeconds) {
  const safe = Math.max(0, Math.floor(totalSeconds || 0))
  const minutes = Math.floor(safe / 60).toString().padStart(2, '0')
  const seconds = (safe % 60).toString().padStart(2, '0')
  return `${minutes}:${seconds}`
}

function formatBytes(bytes) {
  if (!bytes) return '0 MB'
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

function readVideoDuration(file) {
  return new Promise((resolve, reject) => {
    const url = URL.createObjectURL(file)
    const probe = document.createElement('video')
    probe.preload = 'metadata'
    probe.onloadedmetadata = () => {
      const duration = probe.duration
      URL.revokeObjectURL(url)
      resolve(Number.isFinite(duration) && duration > 0 ? duration : 0)
    }
    probe.onerror = () => {
      URL.revokeObjectURL(url)
      reject(new Error('Could not read this video file. Try an mp4, webm, or mov file.'))
    }
    probe.src = url
  })
}

export default function VideoUploadPanel({
  topic,
  setTranscript,
  onTranscribingChange,
  onMediaReady,
  resetKey,
  visionEnabled = true,
  limits = null,
  localAiOffline = false,
}) {
  // Two ceilings apply. The backend publishes its own, but a hosted deployment
  // also sits behind a platform request-body cap it cannot raise, and that one
  // rejects the upload before any application code runs. Enforce the smaller of
  // the two at file-selection time so the user is told immediately rather than
  // after the transcript step has already run.
  const serverMaxVideoBytes = Number(limits?.max_video_bytes) || FALLBACK_MAX_UPLOAD_VIDEO_BYTES
  const maxVideoBytes = localAiHasBodyCap()
    ? Math.min(serverMaxVideoBytes, HOSTED_UPLOAD_LIMIT_BYTES)
    : serverMaxVideoBytes
  const maxRecordingSeconds = Number(limits?.max_recording_seconds) || FALLBACK_MAX_RECORDING_SECONDS
  const inputRef = useRef(null)
  const previewUrlRef = useRef('')

  const [processing, setProcessing] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [fileName, setFileName] = useState('')
  const [fileSize, setFileSize] = useState(0)
  const [duration, setDuration] = useState(0)
  const [previewUrl, setPreviewUrl] = useState('')

  useEffect(() => { onTranscribingChange?.(processing) }, [processing, onTranscribingChange])

  useEffect(() => {
    if (resetKey === undefined) return
    resetPanel()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [resetKey])

  useEffect(() => () => {
    if (previewUrlRef.current) URL.revokeObjectURL(previewUrlRef.current)
  }, [])

  function resetPanel() {
    setProcessing(false)
    setError('')
    setNotice('')
    setFileName('')
    setFileSize(0)
    setDuration(0)
    if (previewUrlRef.current) URL.revokeObjectURL(previewUrlRef.current)
    previewUrlRef.current = ''
    setPreviewUrl('')
    if (inputRef.current) inputRef.current.value = ''
  }

  async function handleFile(file) {
    setError('')
    setNotice('')
    onMediaReady?.(null)
    if (!file) return

    const looksLikeVideo = file.type.startsWith('video/') || ACCEPTED_EXTENSIONS.test(file.name)
    if (!looksLikeVideo) {
      setError('Please choose a video file (mp4, webm, or mov).')
      return
    }
    if (file.size > maxVideoBytes) {
      setError(
        localAiHasBodyCap() && maxVideoBytes === HOSTED_UPLOAD_LIMIT_BYTES
          ? `This file is ${formatBytes(file.size)}. The hosted backend accepts at most ${formatBytes(maxVideoBytes)} per upload, so visual analysis of a full recording needs Clarivo running locally.`
          : `This file is ${formatBytes(file.size)}, over the ${formatBytes(maxVideoBytes)} this backend accepts.`,
      )
      return
    }

    setProcessing(true)
    setNotice('Reading video…')
    try {
      const rawDuration = await readVideoDuration(file)
      const durationSeconds = Math.max(1, Math.round(rawDuration))
      if (durationSeconds > maxRecordingSeconds) {
        throw new Error(`This video is longer than ${Math.round(maxRecordingSeconds / 60)} minutes. Please upload a shorter clip.`)
      }

      setNotice('Extracting audio…')
      const wavBlob = await compressedAudioToWav(file, 16000)

      setNotice('Creating transcript…')
      const transcription = await transcribeAudio(wavBlob, { durationSeconds, topic })
      setTranscript(transcription.text || '')

      if (previewUrlRef.current) URL.revokeObjectURL(previewUrlRef.current)
      const url = URL.createObjectURL(file)
      previewUrlRef.current = url
      setPreviewUrl(url)
      setFileName(file.name)
      setFileSize(file.size)
      setDuration(durationSeconds)
      setNotice('Transcript ready. Review it before analysis.')

      onMediaReady?.({
        audioBlob: wavBlob,
        videoBlob: file,
        durationSeconds,
        audioMimeType: wavBlob.type || 'audio/wav',
        videoMimeType: file.type || 'video/mp4',
        audioSizeBytes: wavBlob.size,
        videoSizeBytes: file.size,
        transcriptionModel: transcription.model,
        transcriptionWordCount: transcription.word_count,
        rawTranscript: transcription.text || '',
        language: 'en',
      })
    } catch (processingError) {
      setNotice('')
      setError(processingError?.message || 'Could not process this video file.')
    } finally {
      setProcessing(false)
    }
  }

  function onInputChange(event) {
    const file = event.target.files?.[0] || null
    handleFile(file)
  }

  return (
    <section className={`voice-recorder media-recorder upload-recorder ${processing ? 'transcribing' : ''}`}>
      <div className="media-recorder-grid">
        <div className="camera-preview-shell">
          {previewUrl ? (
            <video className="camera-preview" src={previewUrl} controls preload="metadata" />
          ) : (
            <div className="camera-placeholder">No file selected</div>
          )}
          <span className="camera-label">Uploaded video</span>
        </div>

        <div className="media-recorder-copy">
          <div className="voice-recorder-top">
            <div>
              <div className="eyebrow">Presentation upload</div>
              <h3>{processing ? 'Preparing transcript…' : 'Upload a recorded video'}</h3>
              {!visionEnabled && (
                <p>
                  {localAiOffline
                    ? 'The machine that runs voice and visual analysis is offline right now. Content feedback still runs on your uploaded video, and voice/visual will come back on their own once it is available again.'
                    : "This backend doesn't run local visual/voice delivery analysis; content feedback will still run on your uploaded video."}
                </p>
              )}
            </div>
            {duration > 0 && <div className="recording-clock">{formatDuration(duration)}</div>}
          </div>

          <div className="voice-recorder-controls">
            <div />
            <input
              ref={inputRef}
              type="file"
              accept="video/mp4,video/webm,video/quicktime,.mp4,.webm,.mov,.m4v"
              onChange={onInputChange}
              disabled={processing}
              style={{ display: 'none' }}
            />
            <button
              type="button"
              className="record-button"
              onClick={() => inputRef.current?.click()}
              disabled={processing}
            >
              {fileName ? 'Choose a different file' : 'Choose a video file'}
            </button>
          </div>
        </div>
      </div>

      {processing && <div className="transcribing-status"><span className="mini-spinner" /><div><strong>{notice || 'Processing…'}</strong></div></div>}
      {notice && !processing && <div className="speech-success">{notice}</div>}
      {error && <div className="speech-error"><span>{error}</span></div>}
      {fileName && !processing && (
        <div className="recording-review">
          <div><strong>{fileName}</strong><span>{formatDuration(duration)} · {formatBytes(fileSize)}</span></div>
        </div>
      )}
    </section>
  )
}
