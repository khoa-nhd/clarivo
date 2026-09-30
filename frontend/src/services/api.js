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
//
// The second address is resolved per call rather than read once at module load,
// because it can be supplied at runtime by a shared link or the in-app field -
// see services/localAiConfig.js.
import { resolveLocalAiBase } from './localAiConfig.js'
import { splitWavForTranscription } from './audioProcessing.js'

const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL || '').replace(/\/$/, '')

function apiUrl(path) {
  return `${API_BASE_URL}${path}`
}

/** Base for the voice/visual endpoints; falls back to the main backend. */
export function localAiBase() {
  return resolveLocalAiBase() || API_BASE_URL
}

function localAiUrl(path) {
  return `${localAiBase()}${path}`
}

/** True when voice/visual go to their own backend rather than the serverless one. */
export function hasDedicatedLocalAi() {
  return resolveLocalAiBase().length > 0
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

/** Where a transcription request should go.
 *
 * Transcription normally belongs to the always-on backend: it needs only the
 * Cloudflare credentials, which both backends have. But the hosted one sits
 * behind a 4.5 MB platform request cap, and the extracted audio of a video
 * passes that at roughly two minutes - so for a five-minute recording the
 * hosted backend is simply the wrong address, and the request fails before any
 * code runs. Send those to the tunnel instead, which has no such ceiling.
 */
function transcriptionTargets(blob) {
  const hosted = apiUrl('/api/transcribe')
  if (!hasDedicatedLocalAi()) return [hosted]
  const local = localAiUrl('/api/transcribe')
  const tooBigForHosted = isHostedApi() && blob && blob.size > HOSTED_UPLOAD_LIMIT_BYTES
  // Either way the other one is kept as a fallback: the tunnel may be off, and
  // the hosted backend may refuse a size the tunnel would have taken.
  return tooBigForHosted ? [local, hosted] : [hosted, local]
}

/** Transcribe one piece. Throws with a readable message on every failure. */
async function transcribeOne(blob, { durationSeconds, topic, failed }) {
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

  // A long recording is sent a minute at a time. Once one address has failed,
  // every later piece would otherwise repeat the same doomed upload before
  // falling back - six wasted megabyte uploads on a five-minute recording.
  const all = transcriptionTargets(blob)
  const usable = all.filter((url) => !failed?.has(url))
  const targets = usable.length ? usable : all

  let lastError = null
  for (const [index, url] of targets.entries()) {
    const isLast = index === targets.length - 1
    // Workers AI intermittently answers "Failed to decode audio file" for a
    // file it accepted moments earlier - seen mid-way through a six-piece
    // recording whose pieces the browser's own decoder all read without
    // complaint. One retry turns that from a lost transcript into a pause.
    for (let attempt = 0; attempt < 2; attempt += 1) {
      try {
        // A body over the platform cap is rejected by the edge before any CORS
        // header is attached, so the browser reports it as a bare network error
        // rather than a status. Treat that like any other failure and move on.
        const response = await fetch(url, { method: 'POST', body: buildBody() })
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
        if (attempt === 0) {
          await new Promise((resolve) => setTimeout(resolve, 1500))
          continue
        }
        // Both attempts failed, so this address is not worth trying for the
        // remaining pieces.
        failed?.add(url)
        if (isLast) throw error
      }
    }
  }
  throw lastError || new Error('Transcription failed.')
}

export async function transcribeAudio(blob, { durationSeconds = 0, topic = '', onProgress } = {}) {
  const pieces = await splitWavForTranscription(blob)
  // Shared across the pieces so a backend that has already failed is not tried
  // again for every one of them.
  const failed = new Set()
  if (pieces.length === 1) {
    onProgress?.({ done: 0, total: 1 })
    return transcribeOne(pieces[0], { durationSeconds, topic, failed })
  }

  // Sequentially, not in parallel: the backend talks to one Workers AI account
  // and several large uploads at once is how a rate limit is met.
  const texts = []
  let words = 0
  let model = null
  let missingParts = 0
  let lastError = null
  for (const [index, piece] of pieces.entries()) {
    onProgress?.({ done: index, total: pieces.length })
    try {
      const part = await transcribeOne(piece, {
        durationSeconds: durationSeconds / pieces.length,
        topic,
        failed,
      })
      const text = typeof part.text === 'string' ? part.text.trim() : ''
      if (text) texts.push(text)
      words += Number(part.word_count) || 0
      model = model || part.model
    } catch (error) {
      // One minute out of five failing must not throw away the other four.
      // The transcript is editable, and the caller is told how much is
      // missing so it can say so rather than presenting a quiet gap.
      missingParts += 1
      lastError = error
    }
  }
  onProgress?.({ done: pieces.length, total: pieces.length })

  if (missingParts === pieces.length) throw lastError || new Error('Transcription failed.')

  return {
    text: texts.join(' '),
    word_count: words,
    duration_seconds: durationSeconds,
    mime_type: blob.type || 'audio/wav',
    size_bytes: blob.size,
    model,
    language: 'en',
    missing_parts: missingParts,
    total_parts: pieces.length,
  }
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
export async function checkLocalAiHealth({ timeoutMs = 8000 } = {}) {
  if (!hasDedicatedLocalAi()) return null
  // A tunnel to a machine that is off does not refuse the connection - it hangs
  // until the browser's own timeout, which is minutes. Without a deadline the
  // page would sit on "checking" instead of saying voice/visual are offline,
  // and the poll that watches for the machine coming back would never fire.
  const abort = new AbortController()
  const timer = setTimeout(() => abort.abort(), timeoutMs)
  try {
    const response = await fetch(localAiUrl('/api/health'), { signal: abort.signal })
    if (!response.ok) throw new Error('Local AI backend unavailable')
    return await response.json()
  } finally {
    clearTimeout(timer)
  }
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
