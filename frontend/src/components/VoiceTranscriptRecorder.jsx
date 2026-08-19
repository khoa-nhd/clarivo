import { useEffect, useRef, useState } from 'react'
import { transcribeAudio } from '../services/api.js'

const MAX_RECORDING_SECONDS = 5 * 60
const AUDIO_BITS_PER_SECOND = 48_000

function formatDuration(totalSeconds) {
  const safe = Math.max(0, Math.floor(totalSeconds || 0))
  const minutes = Math.floor(safe / 60).toString().padStart(2, '0')
  const seconds = (safe % 60).toString().padStart(2, '0')
  return `${minutes}:${seconds}`
}

function chooseMimeType() {
  const candidates = [
    'audio/webm;codecs=opus',
    'audio/webm',
    'audio/ogg;codecs=opus',
    'audio/mp4',
  ]
  return candidates.find((type) => MediaRecorder.isTypeSupported?.(type)) || ''
}

export default function VoiceTranscriptRecorder({
  topic,
  setTranscript,
  onRecordingChange,
  onTranscribingChange,
  onAudioReady,
  resetKey,
}) {
  const mediaRecorderRef = useRef(null)
  const streamRef = useRef(null)
  const chunksRef = useRef([])
  const timerRef = useRef(null)
  const startedAtRef = useRef(0)
  const analyserFrameRef = useRef(null)
  const audioContextRef = useRef(null)
  const currentUrlRef = useRef('')

  const [supported, setSupported] = useState(true)
  const [recording, setRecording] = useState(false)
  const [transcribing, setTranscribing] = useState(false)
  const [elapsed, setElapsed] = useState(0)
  const [level, setLevel] = useState(0)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [recordedBlob, setRecordedBlob] = useState(null)
  const [recordedDuration, setRecordedDuration] = useState(0)
  const [audioUrl, setAudioUrl] = useState('')

  useEffect(() => {
    setSupported(Boolean(navigator.mediaDevices?.getUserMedia && globalThis.MediaRecorder))
    return () => cleanupAll()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  useEffect(() => {
    onRecordingChange?.(recording)
  }, [recording, onRecordingChange])

  useEffect(() => {
    onTranscribingChange?.(transcribing)
  }, [transcribing, onTranscribingChange])

  useEffect(() => {
    if (resetKey === undefined) return
    resetRecorderUi()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [resetKey])

  function stopTimer() {
    clearInterval(timerRef.current)
    timerRef.current = null
  }

  function stopLevelMeter() {
    cancelAnimationFrame(analyserFrameRef.current)
    analyserFrameRef.current = null
    setLevel(0)
    if (audioContextRef.current) {
      audioContextRef.current.close().catch(() => {})
      audioContextRef.current = null
    }
  }

  function releaseStream() {
    streamRef.current?.getTracks().forEach((track) => track.stop())
    streamRef.current = null
    stopLevelMeter()
  }

  function cleanupAll() {
    stopTimer()
    try {
      if (mediaRecorderRef.current?.state === 'recording') mediaRecorderRef.current.stop()
    } catch {
      // Already stopped.
    }
    releaseStream()
    if (currentUrlRef.current) URL.revokeObjectURL(currentUrlRef.current)
    currentUrlRef.current = ''
  }

  function resetRecorderUi() {
    cleanupAll()
    setRecording(false)
    setTranscribing(false)
    setElapsed(0)
    setError('')
    setNotice('')
    setRecordedBlob(null)
    setRecordedDuration(0)
    setAudioUrl('')
  }

  function startLevelMeter(stream) {
    try {
      const AudioContext = globalThis.AudioContext || globalThis.webkitAudioContext
      if (!AudioContext) return
      const context = new AudioContext()
      const analyser = context.createAnalyser()
      analyser.fftSize = 256
      analyser.smoothingTimeConstant = 0.78
      context.createMediaStreamSource(stream).connect(analyser)
      audioContextRef.current = context

      const values = new Uint8Array(analyser.frequencyBinCount)
      const draw = () => {
        analyser.getByteFrequencyData(values)
        const average = values.reduce((sum, value) => sum + value, 0) / values.length
        setLevel(Math.min(1, average / 90))
        analyserFrameRef.current = requestAnimationFrame(draw)
      }
      draw()
    } catch {
      // Level meter is cosmetic; recording still works without it.
    }
  }

  async function runTranscription(blob, durationSeconds) {
    if (!blob) return
    setTranscribing(true)
    setError('')
    setNotice('Uploading the recording and transcribing it in English with Whisper…')

    try {
      const result = await transcribeAudio(blob, {
        durationSeconds,
        topic,
      })
      setTranscript(result.text || '')
      setNotice('Transcript ready. Review and correct it below before adding the session to the queue.')
      onAudioReady?.({
        blob,
        durationSeconds,
        mimeType: blob.type || result.mime_type || 'audio/webm',
        sizeBytes: blob.size,
        transcriptionModel: result.model,
        transcriptionWordCount: result.word_count,
        language: 'en',
      })
    } catch (transcriptionError) {
      setNotice('')
      setError(transcriptionError?.message || 'Could not transcribe the recording.')
    } finally {
      setTranscribing(false)
    }
  }

  async function startRecording() {
    if (!supported || recording || transcribing) return
    setError('')
    setNotice('')
    setElapsed(0)
    setRecordedBlob(null)
    setRecordedDuration(0)

    if (currentUrlRef.current) URL.revokeObjectURL(currentUrlRef.current)
    currentUrlRef.current = ''
    setAudioUrl('')

    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
          channelCount: 1,
        },
      })
      streamRef.current = stream
      startLevelMeter(stream)

      const mimeType = chooseMimeType()
      const recorder = new MediaRecorder(stream, {
        ...(mimeType ? { mimeType } : {}),
        audioBitsPerSecond: AUDIO_BITS_PER_SECOND,
      })

      mediaRecorderRef.current = recorder
      chunksRef.current = []

      recorder.ondataavailable = (event) => {
        if (event.data?.size > 0) chunksRef.current.push(event.data)
      }

      recorder.onerror = (event) => {
        setError(event.error?.message || 'The browser could not record microphone audio.')
      }

      recorder.onstop = () => {
        stopTimer()
        setRecording(false)
        const durationSeconds = Math.max(
          1,
          Math.round((Date.now() - startedAtRef.current) / 1000),
        )
        setRecordedDuration(durationSeconds)

        const blob = new Blob(chunksRef.current, {
          type: recorder.mimeType || mimeType || 'audio/webm',
        })
        setRecordedBlob(blob)
        releaseStream()

        const url = URL.createObjectURL(blob)
        currentUrlRef.current = url
        setAudioUrl(url)
        runTranscription(blob, durationSeconds)
      }

      startedAtRef.current = Date.now()
      setRecording(true)
      recorder.start(1000)

      timerRef.current = setInterval(() => {
        const seconds = Math.floor((Date.now() - startedAtRef.current) / 1000)
        setElapsed(seconds)
        if (seconds >= MAX_RECORDING_SECONDS && recorder.state === 'recording') {
          recorder.stop()
        }
      }, 500)
    } catch (permissionError) {
      releaseStream()
      setRecording(false)
      const name = permissionError?.name || ''
      if (name === 'NotAllowedError' || name === 'SecurityError') {
        setError('Microphone permission was denied. Allow microphone access in your browser, then try again.')
      } else if (name === 'NotFoundError') {
        setError('No microphone was found. Check Windows input settings and try again.')
      } else {
        setError(permissionError?.message || 'Could not start microphone recording.')
      }
    }
  }

  function stopRecording() {
    if (mediaRecorderRef.current?.state !== 'recording') return
    setNotice('Finishing the recording…')
    try {
      mediaRecorderRef.current.stop()
    } catch (stopError) {
      setError(stopError?.message || 'Could not stop the recording cleanly.')
    }
  }

  const canRetry = Boolean(recordedBlob) && !recording && !transcribing

  return (
    <section className={`voice-recorder ${recording ? 'recording' : ''} ${transcribing ? 'transcribing' : ''}`}>
      <div className="voice-recorder-top">
        <div>
          <div className="eyebrow">English microphone recording</div>
          <h3>
            {recording
              ? 'Recording your explanation…'
              : transcribing
                ? 'Creating your transcript…'
                : 'Record first, edit the transcript second'}
          </h3>
          <p>
            The browser records the original audio, Whisper turns it into English text, and you can edit that text before Qwen analyzes it.
            The same recording is kept locally with the session so Delivery analysis can use it later.
          </p>
        </div>
        <div className="recording-clock" aria-label="Recording duration">
          <span className="recording-dot" />
          {formatDuration(recording ? elapsed : recordedDuration || elapsed)}
        </div>
      </div>

      <div className="audio-level-shell" aria-label="Microphone level">
        <div className="audio-level-track">
          <span style={{ width: `${Math.max(recording ? level * 100 : 0, recording ? 3 : 0)}%` }} />
        </div>
        <small>{recording ? 'Microphone level' : 'English only · maximum 5 minutes'}</small>
      </div>

      <div className="voice-recorder-controls">
        <div className="audio-format-note">
          <strong>One recording, two uses</strong>
          <span>Transcript now · delivery metrics later</span>
        </div>

        {!recording ? (
          <button type="button" className="record-button" onClick={startRecording} disabled={!supported || transcribing}>
            <span className="mic-icon">●</span>
            {recordedBlob ? 'Record again' : 'Start recording'}
          </button>
        ) : (
          <button type="button" className="stop-record-button" onClick={stopRecording}>
            <span className="stop-icon" />
            Stop & transcribe
          </button>
        )}
      </div>

      {!supported && (
        <div className="speech-warning">
          This browser cannot record microphone audio with MediaRecorder. Use a current Chrome, Edge, or another modern browser, or paste a transcript manually.
        </div>
      )}

      {transcribing && (
        <div className="transcribing-status">
          <span className="mini-spinner" />
          <div>
            <strong>Whisper is transcribing your recording</strong>
            <p>Keep this page open. You will be able to edit the transcript as soon as it finishes.</p>
          </div>
        </div>
      )}

      {notice && !transcribing && <div className="speech-success">{notice}</div>}
      {error && (
        <div className="speech-error audio-error-row">
          <span>{error}</span>
          {canRetry && (
            <button type="button" className="inline-retry-button" onClick={() => runTranscription(recordedBlob, recordedDuration)}>
              Retry transcription
            </button>
          )}
        </div>
      )}

      {audioUrl && !recording && (
        <div className="recording-review">
          <div>
            <strong>Recorded audio</strong>
            <span>{formatDuration(recordedDuration)} · saved for this draft</span>
          </div>
          <audio controls src={audioUrl} preload="metadata" />
        </div>
      )}
    </section>
  )
}
