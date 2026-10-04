// Clarivo talks to one backend.
//
//   VITE_API_BASE_URL  the deployed serverless backend (Vercel). Serves
//                      transcription, content analysis, voice analysis and the
//                      Q&A drills. Left blank in development, where the Vite
//                      dev server proxies /api to 127.0.0.1:8000.
//
// Voice and visual analysis were briefly split onto a second backend reached
// over a Cloudflare Tunnel, so the OpenVINO stack could serve them from a
// laptop. That is gone: everything goes to the one address again. Running the
// project locally still gives the full OpenVINO stack, because the local
// backend is then the only backend.
const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL || '').replace(/\/$/, '')

function apiUrl(path) {
  return `${API_BASE_URL}${path}`
}

// A hosted backend is one reached through an absolute URL. The local dev server
// proxies /api to 127.0.0.1:8000 and has no upload ceiling, so the guard below
// only applies to the deployed case.
export function isHostedApi() {
  return API_BASE_URL.length > 0
}

// Vercel rejects a function request body larger than 4.5 MB with a 413 before
// the request reaches any application code, so there is nothing the backend can
// do about it. 4.4 MB leaves room for the multipart envelope.
export const HOSTED_UPLOAD_LIMIT_BYTES = Math.floor(4.4 * 1024 * 1024)

// The browser uploads 16 kHz mono 16-bit WAV.
const WAV_BYTES_PER_SECOND = 16000 * 2

// The audio is not the whole request: there is a multipart envelope and the
// transcript field beside it, and the transcript may run to the backend's
// 20,000-character ceiling. Reserving room for both keeps a recording that the
// browser accepted from being refused by the platform on arrival.
const REQUEST_OVERHEAD_BYTES = 64 * 1024

/** The longest recording whose WAV still fits the hosted request cap. */
export function hostedAudioSecondsLimit() {
  return Math.floor((HOSTED_UPLOAD_LIMIT_BYTES - REQUEST_OVERHEAD_BYTES) / WAV_BYTES_PER_SECOND)
}

function describeLimit() {
  const seconds = hostedAudioSecondsLimit()
  const minutes = Math.floor(seconds / 60)
  return `${minutes}m${String(seconds % 60).padStart(2, '0')}s`
}

function assertUploadFits(blob, label) {
  if (!isHostedApi() || !blob || blob.size <= HOSTED_UPLOAD_LIMIT_BYTES) return
  const actual = (blob.size / 1024 / 1024).toFixed(1)
  const cap = (HOSTED_UPLOAD_LIMIT_BYTES / 1024 / 1024).toFixed(1)
  throw new Error(
    `${label} is ${actual} MB, over the ${cap} MB the hosted backend can accept. ` +
    `Keep recordings under about ${describeLimit()}, or run Clarivo locally for full-length analysis.`,
  )
}

async function readPayload(response) {
  try {
    return await response.json()
  } catch {
    return null
  }
}

function errorMessage(response, payload) {
  const detail = payload?.detail
  return typeof detail === 'string'
    ? detail
    : detail?.message || payload?.message || `Request failed (${response.status})`
}

/** POST the recording to /api/transcribe, with one retry.
 *
 * Workers AI intermittently answers "Failed to decode audio file" for a file it
 * accepted moments earlier - three times across one measured run. One retry
 * turns that from a lost transcript into a pause.
 */
async function transcribeOnce(blob, { durationSeconds, topic }) {
  const extension = blob.type.includes('wav') ? 'wav'
    : blob.type.includes('ogg') ? 'ogg'
      : blob.type.includes('mp4') ? 'm4a' : 'webm'
  const buildBody = () => {
    const formData = new FormData()
    formData.append('audio', blob, `presentation.${extension}`)
    formData.append('duration_seconds', String(durationSeconds || 0))
    formData.append('topic', topic || '')
    return formData
  }

  let lastError = null
  for (let attempt = 0; attempt < 2; attempt += 1) {
    try {
      const response = await fetch(apiUrl('/api/transcribe'), { method: 'POST', body: buildBody() })
      const payload = await readPayload(response)
      if (!response.ok) throw new Error(errorMessage(response, payload))
      // A 2xx whose body is not an object - an empty body, or the literal
      // `null` - used to be handed back as-is, and the caller crashed reading
      // `.text` off it. That surfaced as "Cannot read properties of null",
      // which says nothing about the backend having answered strangely.
      if (!payload || typeof payload !== 'object') {
        throw new Error(
          'The transcription service answered without a transcript. Retry, or type the transcript in by hand.',
        )
      }
      return payload
    } catch (error) {
      lastError = error
      if (attempt === 0) await new Promise((resolve) => setTimeout(resolve, 1500))
    }
  }
  throw lastError || new Error('Transcription failed.')
}

export async function transcribeAudio(blob, { durationSeconds = 0, topic = '' } = {}) {
  assertUploadFits(blob, 'The recording')
  return transcribeOnce(blob, { durationSeconds, topic })
}

export async function analyzeSession(session) {
  const response = await fetch(apiUrl('/api/analyze'), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      topic: session.topic,
      target_audience: session.targetAudience,
      transcript: session.transcript,
      reference_content: session.referenceContent || null,
    }),
  })

  const payload = await readPayload(response)
  if (!response.ok) throw new Error(errorMessage(response, payload))
  return payload
}

export async function checkHealth() {
  const response = await fetch(apiUrl('/api/health'))
  if (!response.ok) throw new Error('Backend unavailable')
  return response.json()
}

export async function analyzeAudioDelivery({ audioWavBlob, transcript, durationSeconds = 0 }) {
  assertUploadFits(audioWavBlob, 'The audio track')
  const formData = new FormData()
  formData.append('audio_wav', audioWavBlob, 'presentation.wav')
  formData.append('transcript', transcript || '')
  formData.append('duration_seconds', String(durationSeconds || 0))

  const response = await fetch(apiUrl('/api/analyze/audio'), {
    method: 'POST',
    body: formData,
  })
  const payload = await readPayload(response)
  if (!response.ok) throw new Error(errorMessage(response, payload))
  return payload
}

export async function analyzeVisionDelivery({ videoBlob, durationSeconds = 0 }) {
  assertUploadFits(videoBlob, 'The camera recording')
  const formData = new FormData()
  const videoExtension = videoBlob?.type?.includes('mp4') ? 'mp4' : 'webm'
  formData.append('video', videoBlob, `camera.${videoExtension}`)
  formData.append('duration_seconds', String(durationSeconds || 0))

  const response = await fetch(apiUrl('/api/analyze/vision'), {
    method: 'POST',
    body: formData,
  })
  const payload = await readPayload(response)
  if (!response.ok) throw new Error(errorMessage(response, payload))
  return payload
}

/** Score visual delivery from a timeline the browser's own models produced.
 *
 * The recording stays in the browser; only what the models saw is sent. That is
 * what makes visual analysis work on the deployed backend at all - the OpenVINO
 * stack is far over the serverless size limit, and a video is far over the
 * request body limit. A minute of timeline is about 47 kB.
 */
export async function analyzeVisionTimeline({ frames, durationSeconds = 0, sampleFps = 2 }) {
  const response = await fetch(apiUrl('/api/analyze/vision-timeline'), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      frames,
      duration_seconds: durationSeconds || 0,
      sample_fps: sampleFps || 2,
    }),
  })
  const payload = await readPayload(response)
  if (!response.ok) throw new Error(errorMessage(response, payload))
  return payload
}

export async function generateDrillChallenges(session, result) {
  const response = await fetch(apiUrl('/api/drills/generate'), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      topic: session.topic,
      target_audience: session.targetAudience,
      transcript: session.transcript,
      reference_content: session.referenceContent || null,
      main_scores: result?.scores || {},
      main_issues: result?.issues || [],
    }),
  })
  const payload = await readPayload(response)
  if (!response.ok) throw new Error(errorMessage(response, payload))
  return payload
}

export async function evaluateDrillRound(session, challenge, answerTranscript) {
  const rounds = session.drill?.rounds || []
  const response = await fetch(apiUrl('/api/drills/evaluate'), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      topic: session.topic,
      target_audience: session.targetAudience,
      reference_content: session.referenceContent || null,
      selected_challenge: challenge,
      answer_transcript: answerTranscript,
      history: rounds.map((round) => ({
        round_number: round.roundNumber,
        challenge_type: round.challenge?.type || 'audience',
        question: round.challenge?.prompt || '',
        answer: round.answer || '',
        scores: round.evaluation?.scores || {},
        feedback: round.evaluation?.feedback || '',
      })),
      current_round: rounds.length + 1,
      max_rounds: session.drill?.maxRounds || 3,
      prior_coverage: session.drill?.coreConceptsCoverage || 0,
      prior_weak_areas: session.drill?.weakAreas || [],
    }),
  })
  const payload = await readPayload(response)
  if (!response.ok) throw new Error(errorMessage(response, payload))
  return payload
}

export async function finalizeDrillSession(session) {
  const rounds = session.drill?.rounds || []
  const response = await fetch(apiUrl('/api/drills/finalize'), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      topic: session.topic,
      target_audience: session.targetAudience,
      reference_content: session.referenceContent || null,
      history: rounds.map((round) => ({
        round_number: round.roundNumber,
        challenge_type: round.challenge?.type || 'audience',
        question: round.challenge?.prompt || '',
        answer: round.answer || '',
        scores: round.evaluation?.scores || {},
        feedback: round.evaluation?.feedback || '',
      })),
      core_concepts_coverage: session.drill?.coreConceptsCoverage || 0,
      remaining_weak_areas: session.drill?.weakAreas || [],
    }),
  })
  const payload = await readPayload(response)
  if (!response.ok) throw new Error(errorMessage(response, payload))
  return payload
}


export async function refreshTopicLibrary(existingTopics = [], count = 5) {
  const response = await fetch(apiUrl('/api/topics/refresh'), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      exclude_titles: existingTopics.map((topic) => topic?.title).filter(Boolean).slice(-30),
      count,
    }),
  })
  const payload = await readPayload(response)
  if (!response.ok) throw new Error(errorMessage(response, payload))
  return Array.isArray(payload?.topics) ? payload.topics : []
}
