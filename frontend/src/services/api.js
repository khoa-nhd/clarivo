const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL || '').replace(/\/$/, '')

function apiUrl(path) {
  return `${API_BASE_URL}${path}`
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

export async function analyzeDelivery({ audioWavBlob, videoBlob, transcript, durationSeconds = 0 }) {
  const formData = new FormData()
  formData.append('audio_wav', audioWavBlob, 'presentation.wav')
  const videoExtension = videoBlob?.type?.includes('mp4') ? 'mp4' : 'webm'
  formData.append('video', videoBlob, `camera.${videoExtension}`)
  formData.append('transcript', transcript || '')
  formData.append('duration_seconds', String(durationSeconds || 0))

  const response = await fetch(apiUrl('/api/analyze/delivery'), {
    method: 'POST',
    body: formData,
  })
  const payload = await readPayload(response)
  if (!response.ok) throw new Error(errorMessage(response, payload))
  return payload
}


export async function analyzeAudioDelivery({ audioWavBlob, transcript, durationSeconds = 0 }) {
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
