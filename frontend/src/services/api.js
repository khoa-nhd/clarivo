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
