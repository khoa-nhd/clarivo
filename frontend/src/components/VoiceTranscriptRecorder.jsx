import { useEffect, useRef, useState } from 'react'
import { transcribeAudio } from '../services/api.js'
import { compressedAudioToWav } from '../services/audioProcessing.js'

const MAX_RECORDING_SECONDS = 5 * 60
const AUDIO_BITS_PER_SECOND = 48_000
const VIDEO_BITS_PER_SECOND = 450_000

function formatDuration(totalSeconds) {
  const safe = Math.max(0, Math.floor(totalSeconds || 0))
  const minutes = Math.floor(safe / 60).toString().padStart(2, '0')
  const seconds = (safe % 60).toString().padStart(2, '0')
  return `${minutes}:${seconds}`
}

function chooseAudioMimeType() {
  const candidates = ['audio/webm;codecs=opus', 'audio/webm', 'audio/ogg;codecs=opus', 'audio/mp4']
  return candidates.find((type) => MediaRecorder.isTypeSupported?.(type)) || ''
}

function chooseVideoMimeType() {
  const candidates = ['video/webm;codecs=vp8', 'video/webm;codecs=vp9', 'video/webm']
  return candidates.find((type) => MediaRecorder.isTypeSupported?.(type)) || ''
}

export default function VoiceTranscriptRecorder({
  topic,
  setTranscript,
  onRecordingChange,
  onTranscribingChange,
  onMediaReady,
  resetKey,
}) {
  const audioRecorderRef = useRef(null)
  const videoRecorderRef = useRef(null)
  const streamRef = useRef(null)
  const audioChunksRef = useRef([])
  const videoChunksRef = useRef([])
  const timerRef = useRef(null)
  const startedAtRef = useRef(0)
  const analyserFrameRef = useRef(null)
  const audioContextRef = useRef(null)
  const audioUrlRef = useRef('')
  const previewRef = useRef(null)
  const stoppedPartsRef = useRef(0)
  const expectedPartsRef = useRef(1)
  const finalizingRef = useRef(false)

  const [supported, setSupported] = useState(true)
  const [recording, setRecording] = useState(false)
  const [transcribing, setTranscribing] = useState(false)
  const [elapsed, setElapsed] = useState(0)
  const [level, setLevel] = useState(0)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [recordedAudio, setRecordedAudio] = useState(null)
  const [recordedVideo, setRecordedVideo] = useState(null)
  const [recordedDuration, setRecordedDuration] = useState(0)
  const [audioUrl, setAudioUrl] = useState('')
  const [cameraCaptured, setCameraCaptured] = useState(false)

  useEffect(() => {
    setSupported(Boolean(navigator.mediaDevices?.getUserMedia && globalThis.MediaRecorder))
    return () => cleanupAll()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  useEffect(() => { onRecordingChange?.(recording) }, [recording, onRecordingChange])
  useEffect(() => { onTranscribingChange?.(transcribing) }, [transcribing, onTranscribingChange])
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
    if (previewRef.current) previewRef.current.srcObject = null
    stopLevelMeter()
  }

  function cleanupAll() {
    stopTimer()
    for (const recorder of [audioRecorderRef.current, videoRecorderRef.current]) {
      try { if (recorder?.state === 'recording') recorder.stop() } catch { /* already stopped */ }
    }
    releaseStream()
    if (audioUrlRef.current) URL.revokeObjectURL(audioUrlRef.current)
    audioUrlRef.current = ''
  }

  function resetRecorderUi() {
    cleanupAll()
    setRecording(false)
    setTranscribing(false)
    setElapsed(0)
    setError('')
    setNotice('')
    setRecordedAudio(null)
    setRecordedVideo(null)
    setRecordedDuration(0)
    setAudioUrl('')
    setCameraCaptured(false)
  }

  function startLevelMeter(stream) {
    try {
      const AudioContext = globalThis.AudioContext || globalThis.webkitAudioContext
      if (!AudioContext) return
      const context = new AudioContext()
      const analyser = context.createAnalyser()
      analyser.fftSize = 256
      analyser.smoothingTimeConstant = 0.78
      context.createMediaStreamSource(new MediaStream(stream.getAudioTracks())).connect(analyser)
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
      // Cosmetic only.
    }
  }

  async function finishMedia(audioBlob, videoBlob, durationSeconds) {
    setTranscribing(true)
    setError('')
    setNotice('Preparing recording…')
    try {
      const [transcription, wavBlob] = await Promise.all([
        transcribeAudio(audioBlob, { durationSeconds, topic }),
        compressedAudioToWav(audioBlob, 16000),
      ])
      setTranscript(transcription.text || '')
      setNotice('Transcript ready. Review it before analysis.')
      onMediaReady?.({
        audioBlob: wavBlob,
        videoBlob: videoBlob || null,
        durationSeconds,
        audioMimeType: wavBlob.type || 'audio/wav',
        videoMimeType: videoBlob?.type || '',
        audioSizeBytes: wavBlob.size,
        videoSizeBytes: videoBlob?.size || 0,
        transcriptionModel: transcription.model,
        transcriptionWordCount: transcription.word_count,
        rawTranscript: transcription.text || '',
        language: 'en',
      })
    } catch (processingError) {
      setNotice('')
      setError(processingError?.message || 'Could not prepare this recording.')
    } finally {
      setTranscribing(false)
    }
  }

  function maybeFinalize() {
    stoppedPartsRef.current += 1
    if (stoppedPartsRef.current < expectedPartsRef.current || finalizingRef.current) return
    finalizingRef.current = true
    stopTimer()
    setRecording(false)
    const durationSeconds = Math.max(1, Math.round((Date.now() - startedAtRef.current) / 1000))
    setRecordedDuration(durationSeconds)

    const audioRecorder = audioRecorderRef.current
    const audioBlob = new Blob(audioChunksRef.current, { type: audioRecorder?.mimeType || 'audio/webm' })
    const videoRecorder = videoRecorderRef.current
    const videoBlob = videoRecorder
      ? new Blob(videoChunksRef.current, { type: videoRecorder.mimeType || 'video/webm' })
      : null

    setRecordedAudio(audioBlob)
    setRecordedVideo(videoBlob)
    setCameraCaptured(Boolean(videoBlob?.size))
    releaseStream()

    if (audioUrlRef.current) URL.revokeObjectURL(audioUrlRef.current)
    const url = URL.createObjectURL(audioBlob)
    audioUrlRef.current = url
    setAudioUrl(url)
    finishMedia(audioBlob, videoBlob, durationSeconds).finally(() => { finalizingRef.current = false })
  }

  async function getRecordingStream() {
    const audio = {
      echoCancellation: true,
      noiseSuppression: true,
      autoGainControl: true,
      channelCount: 1,
    }
    try {
      return await navigator.mediaDevices.getUserMedia({
        audio,
        video: {
          width: { ideal: 640 },
          height: { ideal: 480 },
          frameRate: { ideal: 15, max: 20 },
          facingMode: 'user',
        },
      })
    } catch (cameraError) {
      if (cameraError?.name === 'NotFoundError' || cameraError?.name === 'OverconstrainedError') {
        setNotice('Camera unavailable. Audio recording will continue.')
        return navigator.mediaDevices.getUserMedia({ audio, video: false })
      }
      throw cameraError
    }
  }

  async function startRecording() {
    if (!supported || recording || transcribing) return
    setError('')
    setNotice('')
    setElapsed(0)
    setRecordedAudio(null)
    setRecordedVideo(null)
    setRecordedDuration(0)
    setCameraCaptured(false)
    onMediaReady?.(null)

    if (audioUrlRef.current) URL.revokeObjectURL(audioUrlRef.current)
    audioUrlRef.current = ''
    setAudioUrl('')

    try {
      const stream = await getRecordingStream()
      streamRef.current = stream
      if (previewRef.current && stream.getVideoTracks().length) {
        previewRef.current.srcObject = stream
        previewRef.current.play().catch(() => {})
      }
      startLevelMeter(stream)

      const audioMimeType = chooseAudioMimeType()
      const audioRecorder = new MediaRecorder(new MediaStream(stream.getAudioTracks()), {
        ...(audioMimeType ? { mimeType: audioMimeType } : {}),
        audioBitsPerSecond: AUDIO_BITS_PER_SECOND,
      })
      audioRecorderRef.current = audioRecorder
      audioChunksRef.current = []
      audioRecorder.ondataavailable = (event) => { if (event.data?.size > 0) audioChunksRef.current.push(event.data) }
      audioRecorder.onerror = (event) => setError(event.error?.message || 'The browser could not record microphone audio.')
      audioRecorder.onstop = maybeFinalize

      const videoTracks = stream.getVideoTracks()
      let videoRecorder = null
      if (videoTracks.length) {
        const videoMimeType = chooseVideoMimeType()
        videoRecorder = new MediaRecorder(new MediaStream(videoTracks), {
          ...(videoMimeType ? { mimeType: videoMimeType } : {}),
          videoBitsPerSecond: VIDEO_BITS_PER_SECOND,
        })
        videoRecorderRef.current = videoRecorder
        videoChunksRef.current = []
        videoRecorder.ondataavailable = (event) => { if (event.data?.size > 0) videoChunksRef.current.push(event.data) }
        videoRecorder.onerror = () => setNotice('Camera recording failed. Audio will continue.')
        videoRecorder.onstop = maybeFinalize
      } else {
        videoRecorderRef.current = null
        videoChunksRef.current = []
      }

      stoppedPartsRef.current = 0
      expectedPartsRef.current = videoRecorder ? 2 : 1
      finalizingRef.current = false
      startedAtRef.current = Date.now()
      setRecording(true)
      audioRecorder.start(1000)
      videoRecorder?.start(1000)

      timerRef.current = setInterval(() => {
        const seconds = Math.floor((Date.now() - startedAtRef.current) / 1000)
        setElapsed(seconds)
        if (seconds >= MAX_RECORDING_SECONDS) stopRecording()
      }, 500)
    } catch (permissionError) {
      releaseStream()
      setRecording(false)
      const name = permissionError?.name || ''
      if (name === 'NotAllowedError' || name === 'SecurityError') {
        setError('Camera or microphone access was denied.')
      } else if (name === 'NotFoundError') {
        setError('No microphone found.')
      } else {
        setError(permissionError?.message || 'Could not start recording.')
      }
    }
  }

  function stopRecording() {
    const recorders = [audioRecorderRef.current, videoRecorderRef.current]
    if (!recorders.some((recorder) => recorder?.state === 'recording')) return
    setNotice('Finishing the recording…')
    for (const recorder of recorders) {
      try { if (recorder?.state === 'recording') recorder.stop() } catch { /* ignore */ }
    }
  }

  const canRetry = Boolean(recordedAudio) && !recording && !transcribing

  return (
    <section className={`voice-recorder media-recorder ${recording ? 'recording' : ''} ${transcribing ? 'transcribing' : ''}`}>
      <div className="media-recorder-grid">
        <div className="camera-preview-shell">
          <video ref={previewRef} className="camera-preview" autoPlay muted playsInline />
          {!recording && !cameraCaptured && <div className="camera-placeholder">Camera preview</div>}
          {!recording && cameraCaptured && <div className="camera-placeholder captured">✓ Camera ready</div>}
          <span className="camera-label">Camera + mic</span>
        </div>

        <div className="media-recorder-copy">
          <div className="voice-recorder-top">
            <div>
              <div className="eyebrow">Presentation recording</div>
              <h3>{recording ? 'Recording…' : transcribing ? 'Preparing transcript…' : 'Record your presentation'}</h3>
              
            </div>
            <div className="recording-clock"><span className="recording-dot" />{formatDuration(recording ? elapsed : recordedDuration || elapsed)}</div>
          </div>

          <div className="audio-level-shell" aria-label="Microphone level">
            <div className="audio-level-track"><span style={{ width: `${Math.max(recording ? level * 100 : 0, recording ? 3 : 0)}%` }} /></div>
            <small>{recording ? 'Mic level' : 'Up to 5 minutes'}</small>
          </div>

          <div className="voice-recorder-controls">
            <div />
            {!recording ? (
              <button type="button" className="record-button" onClick={startRecording} disabled={!supported || transcribing}><span className="mic-icon">●</span>{recordedAudio ? 'Record again' : 'Start recording'}</button>
            ) : (
              <button type="button" className="stop-record-button" onClick={stopRecording}><span className="stop-icon" />Stop & transcribe</button>
            )}
          </div>
        </div>
      </div>

      {!supported && <div className="speech-warning">Recording is not supported in this browser.</div>}
      {transcribing && <div className="transcribing-status"><span className="mini-spinner" /><div><strong>Creating transcript…</strong></div></div>}
      {notice && !transcribing && <div className="speech-success">{notice}</div>}
      {error && <div className="speech-error audio-error-row"><span>{error}</span>{canRetry && <button type="button" className="inline-retry-button" onClick={() => finishMedia(recordedAudio, recordedVideo, recordedDuration)}>Retry processing</button>}</div>}
      {audioUrl && !recording && <div className="recording-review"><div><strong>Recording</strong><span>{formatDuration(recordedDuration)} · {cameraCaptured ? 'camera + audio' : 'audio only'}</span></div><audio controls src={audioUrl} preload="metadata" /></div>}
    </section>
  )
}
