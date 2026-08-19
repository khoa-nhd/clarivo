import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { analyzeSession } from '../services/api.js'
import { deleteSessionAudio, saveSessionAudio } from '../services/audioStore.js'

// Keep the old storage key so existing local sessions survive the UI rename to Clarivo.
const STORAGE_KEY = 'explaincoach.sessions.v1'

function loadSessions() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (!raw) return []
    const parsed = JSON.parse(raw)
    if (!Array.isArray(parsed)) return []

    // A browser refresh may interrupt an HTTP request. Put interrupted jobs
    // back into the queue so they can safely run again.
    return parsed.map((session) =>
      session.status === 'processing'
        ? { ...session, status: 'queued', error: null }
        : session,
    )
  } catch {
    return []
  }
}

function makeId() {
  if (globalThis.crypto?.randomUUID) return crypto.randomUUID()
  return `${Date.now()}-${Math.random().toString(16).slice(2)}`
}

export function useSessionQueue() {
  const [sessions, setSessions] = useState(loadSessions)
  const [activeId, setActiveId] = useState(() => loadSessions()[0]?.id ?? null)
  const inFlightIdRef = useRef(null)

  useEffect(() => {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(sessions))
  }, [sessions])

  const patchSession = useCallback((id, patch) => {
    setSessions((current) =>
      current.map((session) =>
        session.id === id ? { ...session, ...patch } : session,
      ),
    )
  }, [])

  useEffect(() => {
    if (inFlightIdRef.current) return

    const next = sessions.find((session) => session.status === 'queued')
    if (!next) return

    inFlightIdRef.current = next.id
    patchSession(next.id, {
      status: 'processing',
      startedAt: new Date().toISOString(),
      error: null,
    })

    analyzeSession(next)
      .then((result) => {
        patchSession(next.id, {
          status: 'complete',
          result,
          completedAt: new Date().toISOString(),
          error: null,
        })
      })
      .catch((error) => {
        patchSession(next.id, {
          status: 'error',
          error: error?.message || 'Unknown analysis error',
          completedAt: new Date().toISOString(),
        })
      })
      .finally(() => {
        inFlightIdRef.current = null
        // Force a state pass even if React batched the completion patch.
        setSessions((current) => [...current])
      })
  }, [sessions, patchSession])

  const addSession = useCallback((draft) => {
    const session = {
      id: makeId(),
      topic: draft.topic.trim(),
      targetAudience: draft.targetAudience,
      transcript: draft.transcript.trim(),
      referenceContent: draft.referenceContent?.trim() || '',
      status: 'queued',
      createdAt: new Date().toISOString(),
      startedAt: null,
      completedAt: null,
      result: null,
      error: null,
      // Raw audio is intentionally NOT serialized into localStorage.
      // Only metadata lives on the session; the Blob is saved in IndexedDB
      // under the same session id for future Delivery analysis.
      audio: draft.audioMeta ? { ...draft.audioMeta, storedLocally: true } : null,
      delivery: null,
      vision: null,
    }

    if (draft.audioBlob) {
      saveSessionAudio(session.id, draft.audioBlob, session.audio || {}).catch((error) => {
        console.warn('Could not persist session audio locally:', error)
      })
    }

    setSessions((current) => [session, ...current])
    setActiveId(session.id)
    return session.id
  }, [])

  const retrySession = useCallback((id) => {
    patchSession(id, {
      status: 'queued',
      error: null,
      result: null,
      startedAt: null,
      completedAt: null,
    })
  }, [patchSession])

  const removeSession = useCallback((id) => {
    if (inFlightIdRef.current === id) return false
    setSessions((current) => current.filter((session) => session.id !== id))
    setActiveId((currentActiveId) => (currentActiveId === id ? null : currentActiveId))
    deleteSessionAudio(id).catch((error) => {
      console.warn('Could not delete local session audio:', error)
    })
    return true
  }, [])

  const updateTranscript = useCallback((id, transcript, options = {}) => {
    const clean = String(transcript || '').trim()
    if (clean.length < 20 || inFlightIdRef.current === id) return false

    setSessions((current) => current.map((session) => {
      if (session.id !== id || session.status === 'processing') return session

      if (options.reanalyze) {
        return {
          ...session,
          transcript: clean,
          status: 'queued',
          result: null,
          error: null,
          startedAt: null,
          completedAt: null,
          updatedAt: new Date().toISOString(),
        }
      }

      return {
        ...session,
        transcript: clean,
        updatedAt: new Date().toISOString(),
      }
    }))
    return true
  }, [])

  const activeSession = useMemo(
    () => sessions.find((session) => session.id === activeId) ?? null,
    [sessions, activeId],
  )

  const counts = useMemo(() => ({
    queued: sessions.filter((item) => item.status === 'queued').length,
    processing: sessions.filter((item) => item.status === 'processing').length,
    complete: sessions.filter((item) => item.status === 'complete').length,
    error: sessions.filter((item) => item.status === 'error').length,
  }), [sessions])

  return {
    sessions,
    activeSession,
    activeId,
    counts,
    addSession,
    setActiveId,
    retrySession,
    removeSession,
    updateTranscript,
    startNewSession: () => setActiveId(null),
  }
}
