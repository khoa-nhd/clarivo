import { useEffect, useRef, useState } from 'react'
import { transcribeAudio } from '../services/api.js'

const MAX_QA_SECONDS = 60

function fmt(totalSeconds) {
  const value = Math.max(0, Math.floor(totalSeconds || 0))
  const minutes = Math.floor(value / 60)
  const remainingSeconds = value % 60
  return `${String(minutes).padStart(2, '0')}:${String(remainingSeconds).padStart(2, '0')}`
}

function chooseMime() {
  const types = ['audio/webm;codecs=opus', 'audio/webm', 'audio/ogg;codecs=opus', 'audio/mp4']
  return types.find((type) => MediaRecorder.isTypeSupported?.(type)) || ''
}

export default function DrillRecorder({ topic, disabled, onSubmit, resetKey }) {
  const recorderRef = useRef(null)
  const streamRef = useRef(null)
  const chunksRef = useRef([])
  const timerRef = useRef(null)
  const startedAtRef = useRef(0)

  const [recording, setRecording] = useState(false)
  const [transcribing, setTranscribing] = useState(false)
  const [elapsed, setElapsed] = useState(0)
  const [answer, setAnswer] = useState('')
  const [error, setError] = useState('')

  useEffect(() => () => cleanup(), [])
  useEffect(() => {
    setAnswer('')
    setError('')
    setElapsed(0)
  }, [resetKey])

  function cleanup() {
    clearInterval(timerRef.current)
    timerRef.current = null
    streamRef.current?.getTracks().forEach((track) => track.stop())
    streamRef.current = null
  }

  async function start() {
    if (disabled || recording || transcribing) return
    setError('')
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true, channelCount: 1 },
        video: false,
      })
      streamRef.current = stream
      const mimeType = chooseMime()
      const recorder = new MediaRecorder(stream, {
        ...(mimeType ? { mimeType } : {}),
        audioBitsPerSecond: 48_000,
      })
      recorderRef.current = recorder
      chunksRef.current = []
      recorder.ondataavailable = (event) => { if (event.data?.size) chunksRef.current.push(event.data) }
      recorder.onstop = async () => {
        const duration = Math.max(1, Math.round((Date.now() - startedAtRef.current) / 1000))
        const blob = new Blob(chunksRef.current, { type: recorder.mimeType || 'audio/webm' })
        cleanup()
        setRecording(false)
        setTranscribing(true)
        try {
          const result = await transcribeAudio(blob, { durationSeconds: duration, topic })
          setAnswer(result.text || '')
        } catch (exc) {
          setError(exc?.message || 'Could not transcribe this Q&A answer. You can type it manually.')
        } finally {
          setTranscribing(false)
        }
      }
      recorder.start(250)
      startedAtRef.current = Date.now()
      setElapsed(0)
      setRecording(true)
      timerRef.current = setInterval(() => {
        const seconds = Math.floor((Date.now() - startedAtRef.current) / 1000)
        setElapsed(seconds)
        if (seconds >= MAX_QA_SECONDS) {
          clearInterval(timerRef.current)
          timerRef.current = null
          try { recorder.stop() } catch { /* noop */ }
        }
      }, 250)
    } catch (exc) {
      cleanup()
      setError(exc?.message || 'Microphone permission was not granted.')
    }
  }

  function stop() {
    if (!recording) return
    clearInterval(timerRef.current)
    timerRef.current = null
    try { recorderRef.current?.stop() } catch { cleanup(); setRecording(false) }
  }

  const canSubmit = !recording && !transcribing && !disabled && answer.trim().length >= 5

  return (
    <div className="drill-recorder">
      <div className="drill-recorder-top">
        <div>
          <span className="delivery-panel-tag">30–60 seconds</span>
          <h4>Your answer</h4>
        </div>
        <span className={`drill-timer ${recording ? 'recording' : ''}`}>{recording ? '● ' : ''}{fmt(elapsed)}</span>
      </div>

      <div className="drill-recorder-actions">
        {!recording ? (
          <button type="button" className="drill-record-button" onClick={start} disabled={disabled || transcribing}>
            {transcribing ? 'Transcribing…' : '● Record answer'}
          </button>
        ) : (
          <button type="button" className="drill-stop-button" onClick={stop}>■ Stop & transcribe</button>
        )}
        <small>Up to 60 seconds</small>
      </div>

      {error ? <div className="drill-inline-error">{error}</div> : null}

      <label className="field drill-answer-field">
        <div className="field-row"><span>Q&A transcript</span><small>{answer.trim() ? answer.trim().split(/\s+/).length : 0} words</small></div>
        <textarea
          value={answer}
          onChange={(event) => setAnswer(event.target.value)}
          placeholder="Review or type your answer."
          disabled={recording || transcribing || disabled}
        />
      </label>

      <div className="drill-recorder-footer">
        
        <button type="button" className="primary-button" disabled={!canSubmit} onClick={() => onSubmit(answer.trim())}>
          Submit answer <span>→</span>
        </button>
      </div>
    </div>
  )
}
