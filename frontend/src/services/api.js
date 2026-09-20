// Clarivo can talk to two backends at once.
//
//   VITE_API_BASE_URL       the always-on serverless backend (Vercel). Serves
//                           transcription, content analysis and the Q&A drills,
//                           all of which are small JSON or short audio.
//   VITE_LOCAL_AI_BASE_URL  optional. A machine running the OpenVINO stack,
//                           reached over a tunnel. Serves the voice and visual
//                           analysis, which need packages and upload sizes a
//                           serverless function cannot provide.
//
// Splitting them means the site keeps working when that machine is off: content
// and Q&A carry on, and only voice/visual report unavailable. Leave the second
// one empty and everything goes to the first, which is the previous behaviour.
const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL || '').replace(/\/$/, '')
const LOCAL_AI_BASE_URL = (import.meta.env.VITE_LOCAL_AI_BASE_URL || '').replace(/\/$/, '')

function apiUrl(path) {
  return `${API_BASE_URL}${path}`
}

/** Base for the voice/visual endpoints; falls back to the main backend. */
export function localAiBase() {
  return LOCAL_AI_BASE_URL || API_BASE_URL
}

function localAiUrl(path) {
  return `${localAiBase()}${path}`
}

/** True when voice/visual go to their own backend rather than the serverless one. */
export function hasDedicatedLocalAi() {
  return LOCAL_AI_BASE_URL.length > 0
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

function describeLimit() {
  const seconds = Math.floor(HOSTED_UPLOAD_LIMIT_BYTES / WAV_BYTES_PER_SECOND)
  const minutes = Math.floor(seconds / 60)
  return `${minutes}m${String(seconds % 60).padStart(2, '0')}s`
}

/** Whether the media endpoints are subject to the serverless body cap. */
export function localAiHasBodyCap() {
  // A tunnel terminates at a real server, which has no such ceiling. The cap
  // only exists when voice/visual are served by the serverless backend itself.
  return isHostedApi() && !hasDedicatedLocalAi()
}

function assertUploadFits(blob, label) {
  if (!localAiHasBodyCap() || !blob || blob.size <= HOSTED_UPLOAD_LIMIT_BYTES) return
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

export async function transcribeAudio(blob, { durationSeconds = 0, topic = '' } = {}) {
  const extension = blob.type.includes('ogg') ? 'ogg' : blob.type.includes('mp4') ? 'm4a' : 'webm'
  const formData = new FormData()
  formData.append('audio', blob, `presentation.${extension}`)
  formData.append('duration_seconds', String(durationSeconds || 0))
  formData.append('topic', topic || '')

  const response = await fetch(apiUrl('/api/transcribe'), {
    method: 'POST',
    body: formData,
  })

  const payload = await readPayload(response)
  if (!response.ok) throw new Error(errorMessage(response, payload))
  return payload
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

/** Capability probe for the voice/visual backend.
 *
 * Only meaningful when a dedicated one is configured; otherwise the main
 * health response already describes it.
 */
export async function checkLocalAiHealth() {
  if (!hasDedicatedLocalAi()) return null
  const response = await fetch(localAiUrl('/api/health'))
  if (!response.ok) throw new Error('Local AI backend unavailable')
  return response.json()
}

export async function analyzeDelivery({ audioWavBlob, videoBlob, transcript, durationSeconds = 0 }) {
  assertUploadFits(audioWavBlob, 'The audio track')
  assertUploadFits(videoBlob, 'The camera recording')
  const formData = new FormData()
  formData.append('audio_wav', audioWavBlob, 'presentation.wav')
  const videoExtension = videoBlob?.type?.includes('mp4') ? 'mp4' : 'webm'
  formData.append('video', videoBlob, `camera.${videoExtension}`)
  formData.append('transcript', transcript || '')
  formData.append('duration_seconds', String(durationSeconds || 0))

  const response = await fetch(localAiUrl('/api/analyze/delivery'), {
    method: 'POST',
    body: formData,
  })
  const payload = await readPayload(response)
  if (!response.ok) throw new Error(errorMessage(response, payload))
  return payload
}


export async function analyzeAudioDelivery({ audioWavBlob, transcript, durationSeconds = 0 }) {
  assertUploadFits(audioWavBlob, 'The audio track')
  const formData = new FormData()
  formData.append('audio_wav', audioWavBlob, 'presentation.wav')
  formData.append('transcript', transcript || '')
  formData.append('duration_seconds', String(durationSeconds || 0))

  const response = await fetch(localAiUrl('/api/analyze/audio'), {
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

  const response = await fetch(localAiUrl('/api/analyze/vision'), {
    method: 'POST',
    body: formData,
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
