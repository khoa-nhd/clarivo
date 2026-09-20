import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { analyzeAudioDelivery, analyzeSession, analyzeVisionDelivery, checkHealth, checkLocalAiHealth, evaluateDrillRound, finalizeDrillSession, generateDrillChallenges, hasDedicatedLocalAi } from '../services/api.js'
import { deleteSessionAudio, getSessionAudio, saveSessionAudio } from '../services/audioStore.js'
import { deleteSessionVideo, getSessionVideo, saveSessionVideo } from '../services/videoStore.js'

const STORAGE_KEY = 'clarivo.sessions.v2'

function loadSessions() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY) || localStorage.getItem('explaincoach.sessions.v1')
    if (!raw) return []
    const parsed = JSON.parse(raw)
    if (!Array.isArray(parsed)) return []
    return parsed.map((session) =>
      ['processing', 'preparing'].includes(session.status)
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

function combineDelivery(audioResult, visionResult) {
  if (!audioResult && !visionResult) return null
  const priorities = []
  for (const item of [...(audioResult?.top_priorities || []), ...(visionResult?.top_priorities || [])]) {
    if (item && !priorities.includes(item)) priorities.push(item)
  }
  return {
    schema_version: 'clarivo-web-delivery-v11-split',
    voice_score: audioResult?.voice_score ?? null,
    visual_score: visionResult?.visual_score ?? null,
    voice: audioResult?.voice ?? null,
    visual: visionResult?.visual ?? null,
    top_priorities: priorities.slice(0, 3),
    meta: {
      engine: 'Clarivo Phase 20 local scoring',
      audio_engine: audioResult?.meta?.engine || null,
      vision_engine: visionResult?.meta?.engine || null,
      audio_confidence: audioResult?.meta?.audio_confidence ?? null,
      vision_confidence: visionResult?.meta?.vision_confidence ?? null,
    },
  }
}


function mainContentOverall(result) {
  const values = Object.values(result?.scores || {}).map(Number).filter(Number.isFinite)
  if (!values.length) return 0
  return Math.round(values.reduce((sum, value) => sum + value, 0) / values.length)
}

function qaOverallSnapshot(result, priorRounds, currentQaOverall) {
  const base = mainContentOverall(result)
  const qaValues = [...priorRounds.map((round) => Number(round?.evaluation?.overall_score)).filter(Number.isFinite), Number(currentQaOverall)].filter(Number.isFinite)
  const qaAverage = qaValues.length ? qaValues.reduce((sum, value) => sum + value, 0) / qaValues.length : base
  // Q&A is a meaningful correction signal, but it cannot overwhelm the full main presentation.
  const rawImpact = Math.round((qaAverage - base) * 0.20)
  const delta = Math.max(-8, Math.min(8, rawImpact))
  return {
    mainOverall: base,
    qaAverage: Math.round(qaAverage),
    overallDelta: delta,
    overallAfterQA: Math.max(0, Math.min(100, base + delta)),
  }
}

function replaceChallengeOfType(currentChallenges, answeredChallenge, nextChallenges) {
  const remaining = (currentChallenges || []).filter((item) => item?.type !== answeredChallenge?.type)
  const replacement = (nextChallenges || []).find((item) => item?.type === answeredChallenge?.type)
  const order = { audience: 0, deep_dive: 1, broaden: 2 }
  return (replacement ? [...remaining, replacement] : remaining)
    .sort((a, b) => (order[a?.type] ?? 9) - (order[b?.type] ?? 9))
}

function audioAvailable(health) {
  const delivery = health?.delivery_analysis
  return Boolean(delivery?.enabled && (delivery?.audio_ready ?? true))
}

function visionAvailable(health) {
  const delivery = health?.delivery_analysis
  return Boolean(delivery?.enabled && (delivery?.vision_ready ?? delivery?.models_ready))
}

export function useSessionQueue() {
  const [sessions, setSessions] = useState(loadSessions)
  const [activeId, setActiveId] = useState(() => loadSessions()[0]?.id ?? null)
  const [backendHealth, setBackendHealth] = useState(null)
  const inFlightIdRef = useRef(null)
  const sessionsRef = useRef(sessions)
  const backendHealthRef = useRef(null)

  const applyHealth = useCallback((health) => {
    backendHealthRef.current = health
    setBackendHealth(health)
    return health
  }, [])

  // Read both backends and merge them into one health object.
  //
  // The main backend describes the AI provider and the drill settings. When a
  // dedicated voice/visual backend is configured, its own capability report
  // replaces delivery_analysis - asking the serverless backend whether OpenVINO
  // is available would always answer no, because it never runs it.
  const probeHealth = useCallback(async () => {
    const main = await checkHealth()
    if (!hasDedicatedLocalAi()) return main
    try {
      const localAi = await checkLocalAiHealth()
      return {
        ...main,
        delivery_analysis: {
          ...(localAi?.delivery_analysis || {}),
          served_by: 'local_ai_backend',
        },
      }
    } catch {
      // The machine behind the tunnel is off. Content and Q&A still work, so
      // report only voice/visual as unavailable rather than failing outright.
      return {
        ...main,
        delivery_analysis: {
          enabled: false,
          audio_ready: false,
          vision_ready: false,
          models_ready: false,
          mode: 'offline',
          served_by: 'local_ai_backend',
          unreachable: true,
        },
      }
    }
  }, [])

  // Re-read the backend capabilities. Returns the freshest value available.
  const refreshHealth = useCallback(async () => {
    try {
      return applyHealth(await probeHealth())
    } catch {
      // Do not downgrade a previously successful reading because of one blip;
      // that would flap the whole delivery UI off and back on.
      if (backendHealthRef.current) return backendHealthRef.current
      return applyHealth({ delivery_analysis: { enabled: false, unreachable: true } })
    }
  }, [applyHealth, probeHealth])

  // The capability probe used to run exactly once, with no retry, and cache a
  // permanent "disabled" result on any failure. Frontend and backend start
  // together and the dev server is ready seconds before uvicorn finishes
  // booting, so losing that race left the app believing local voice/visual
  // analysis did not exist - stamping every session "Voice unavailable /
  // Visual unavailable" until the user manually reloaded the page.
  useEffect(() => {
    let cancelled = false
    let timer = null
    let attempt = 0
    const backoffMs = [400, 800, 1600, 3000, 5000]

    const probe = async () => {
      if (cancelled) return
      try {
        applyHealth(await probeHealth())
      } catch {
        if (cancelled) return
        if (!backendHealthRef.current) {
          applyHealth({ delivery_analysis: { enabled: false, unreachable: true } })
        }
        if (attempt < 8) {
          const delay = backoffMs[Math.min(attempt, backoffMs.length - 1)]
          attempt += 1
          timer = setTimeout(probe, delay)
        }
      }
    }

    probe()
    return () => { cancelled = true; if (timer) clearTimeout(timer) }
  }, [applyHealth, probeHealth])

  // Re-probe when the user returns to the tab, which is when a backend that was
  // restarted in the meantime would otherwise still look absent.
  useEffect(() => {
    const onWake = () => { if (document.visibilityState !== 'hidden') refreshHealth() }
    window.addEventListener('focus', onWake)
    document.addEventListener('visibilitychange', onWake)
    return () => {
      window.removeEventListener('focus', onWake)
      document.removeEventListener('visibilitychange', onWake)
    }
  }, [refreshHealth])

  // Keep watching while the voice/visual backend is offline.
  //
  // The retry loop above only fires when the health request itself fails, and
  // once the backends were split that stopped covering this case: probeHealth
  // handles an unreachable local-AI backend internally and returns a perfectly
  // successful result that merely says "offline". So the machine behind the
  // tunnel could come back and the page would never notice. This is the poll
  // that closes that gap - one small GET while it is down, stopping as soon as
  // it answers.
  const localAiUnreachable = Boolean(
    hasDedicatedLocalAi() && backendHealth?.delivery_analysis?.unreachable,
  )
  useEffect(() => {
    if (!localAiUnreachable) return undefined
    const timer = setInterval(() => {
      if (document.visibilityState !== 'hidden') refreshHealth()
    }, 15000)
    return () => clearInterval(timer)
  }, [localAiUnreachable, refreshHealth])

  useEffect(() => {
    sessionsRef.current = sessions
    localStorage.setItem(STORAGE_KEY, JSON.stringify(sessions))
  }, [sessions])

  const patchSession = useCallback((id, patch) => {
    setSessions((current) => current.map((session) => session.id === id ? { ...session, ...patch } : session))
  }, [])

  const localAudioEnabled = audioAvailable(backendHealth)
  const localVisionEnabled = visionAvailable(backendHealth)
  const localDeliveryEnabled = localAudioEnabled || localVisionEnabled
  const backendUnreachable = Boolean(backendHealth?.delivery_analysis?.unreachable)
  // Distinguishes "this backend was never built to run it" from "the machine
  // that runs it is currently off", which are very different things to tell a
  // user staring at a disabled panel.
  const localAiOffline = backendHealth?.delivery_analysis?.mode === 'offline'
  const uploadLimits = backendHealth?.delivery_analysis?.limits ?? null

  useEffect(() => {
    if (inFlightIdRef.current) return
    const next = sessions.find((session) => session.status === 'queued')
    if (!next) return

    inFlightIdRef.current = next.id

    ;(async () => {
      // If this session carries recorded media but local analysis currently
      // looks unavailable, that may just be a stale snapshot from before the
      // backend finished booting. Confirm once instead of permanently marking
      // the session unavailable.
      let health = backendHealthRef.current
      const wantsLocal = Boolean(next.audio || next.video)
      const needsAudio = Boolean(next.audio) && !audioAvailable(health)
      const needsVision = Boolean(next.video) && !visionAvailable(health)
      if (wantsLocal && (needsAudio || needsVision)) {
        health = await refreshHealth()
      }
      const audioEnabled = audioAvailable(health)
      const visionEnabled = visionAvailable(health)

      patchSession(next.id, {
        status: 'processing',
        startedAt: new Date().toISOString(),
        error: null,
        deliveryError: null,
        analysisState: {
          content: 'processing',
          audio: next.audio && audioEnabled ? 'processing' : 'unavailable',
          vision: next.video && visionEnabled ? 'processing' : 'unavailable',
        },
      })

      let audioMedia = null
      let videoMedia = null
      if (next.audio && audioEnabled) audioMedia = await getSessionAudio(next.id).catch(() => null)
      if (next.video && visionEnabled) videoMedia = await getSessionVideo(next.id).catch(() => null)

      const contentPromise = analyzeSession(next)
      const audioPromise = audioMedia?.blob
        ? analyzeAudioDelivery({
            audioWavBlob: audioMedia.blob,
            transcript: next.audio?.rawTranscript || next.transcript,
            durationSeconds: next.audio?.durationSeconds || 0,
          })
        : Promise.resolve(null)
      const visionPromise = videoMedia?.blob
        ? analyzeVisionDelivery({
            videoBlob: videoMedia.blob,
            durationSeconds: next.video?.durationSeconds || next.audio?.durationSeconds || 0,
          })
        : Promise.resolve(null)

      const [contentResult, audioResult, visionResult] = await Promise.allSettled([
        contentPromise,
        audioPromise,
        visionPromise,
      ])

      const audioValue = audioResult.status === 'fulfilled' ? audioResult.value : null
      const visionValue = visionResult.status === 'fulfilled' ? visionResult.value : null
      const delivery = combineDelivery(audioValue, visionValue)
      const deliveryErrors = [
        audioResult.status === 'rejected' ? `Voice: ${audioResult.reason?.message || 'analysis failed'}` : null,
        visionResult.status === 'rejected' ? `Visual: ${visionResult.reason?.message || 'analysis failed'}` : null,
      ].filter(Boolean)

      let initialDrill = null
      let initialDrillError = null
      if (contentResult.status === 'fulfilled') {
        patchSession(next.id, {
          drill: {
            ...(next.drill || {}),
            state: 'generating',
            maxRounds: next.drill?.maxRounds || 3,
            rounds: next.drill?.rounds || [],
          },
        })
        try {
          initialDrill = await generateDrillChallenges(next, contentResult.value)
        } catch (error) {
          initialDrillError = error?.message || 'Could not generate follow-up challenges.'
        }
      }

      if (contentResult.status === 'rejected') {
        patchSession(next.id, {
          status: 'error',
          error: contentResult.reason?.message || 'Unknown content analysis error',
          delivery,
          deliveryError: deliveryErrors.join(' · ') || null,
          analysisState: {
            content: 'error',
            audio: audioResult.status === 'rejected' ? 'error' : audioValue ? 'complete' : 'unavailable',
            vision: visionResult.status === 'rejected' ? 'error' : visionValue ? 'complete' : 'unavailable',
          },
          completedAt: new Date().toISOString(),
        })
        return
      }

      patchSession(next.id, {
        status: 'complete',
        result: contentResult.value,
        delivery,
        deliveryError: deliveryErrors.join(' · ') || null,
        drill: initialDrill
          ? {
              state: initialDrill.drill_recommended === false ? 'skipped' : 'ready',
              maxRounds: next.drill?.maxRounds || 3,
              challenges: initialDrill.drill_recommended === false ? [] : (initialDrill.challenges || []),
              coreConceptsCoverage: initialDrill.core_concepts_coverage || 0,
              weakAreas: initialDrill.weak_areas || [],
              coverageStatus: initialDrill.coverage_status || 'developing',
              rounds: next.drill?.rounds || [],
              finalSummary: null,
              stopReason: initialDrill.skip_reason || '',
              skipReason: initialDrill.skip_reason || '',
              drillRecommended: initialDrill.drill_recommended !== false,
              error: null,
            }
          : {
              state: 'error',
              maxRounds: next.drill?.maxRounds || 3,
              challenges: [],
              coreConceptsCoverage: 0,
              weakAreas: [],
              coverageStatus: 'developing',
              rounds: next.drill?.rounds || [],
              finalSummary: null,
              stopReason: '',
              error: initialDrillError || 'Could not generate follow-up challenges.',
            },
        analysisState: {
          content: 'complete',
          audio: audioResult.status === 'rejected' ? 'error' : audioValue ? 'complete' : 'unavailable',
          vision: visionResult.status === 'rejected' ? 'error' : visionValue ? 'complete' : 'unavailable',
        },
        completedAt: new Date().toISOString(),
        error: null,
      })
    })()
      .finally(() => {
        inFlightIdRef.current = null
        setSessions((current) => [...current])
      })
  }, [sessions, patchSession, refreshHealth, localAudioEnabled, localVisionEnabled])

  const addSession = useCallback((draft) => {
    const session = {
      id: makeId(),
      topic: draft.topic.trim(),
      targetAudience: draft.targetAudience,
      transcript: draft.transcript.trim(),
      referenceContent: draft.referenceContent?.trim() || '',
      topicProfile: draft.topicProfile || null,
      status: draft.audioBlob || draft.videoBlob ? 'preparing' : 'queued',
      createdAt: new Date().toISOString(),
      startedAt: null,
      completedAt: null,
      result: null,
      error: null,
      audio: draft.audioMeta ? { ...draft.audioMeta, storedLocally: true } : null,
      video: draft.videoMeta ? { ...draft.videoMeta, storedLocally: true } : null,
      delivery: null,
      deliveryError: null,
      drill: {
        state: 'idle',
        maxRounds: backendHealth?.learning_loop?.max_rounds || 3,
        challenges: [],
        coreConceptsCoverage: 0,
        weakAreas: [],
        coverageStatus: 'developing',
        rounds: [],
        finalSummary: null,
        stopReason: '',
        error: null,
      },
      analysisState: { content: 'queued', audio: 'queued', vision: 'queued' },
    }

    setSessions((current) => [session, ...current])
    setActiveId(session.id)

    if (draft.audioBlob || draft.videoBlob) {
      Promise.all([
        draft.audioBlob ? saveSessionAudio(session.id, draft.audioBlob, session.audio || {}) : Promise.resolve(true),
        draft.videoBlob ? saveSessionVideo(session.id, draft.videoBlob, session.video || {}) : Promise.resolve(true),
      ])
        .then(() => patchSession(session.id, { status: 'queued' }))
        .catch((error) => patchSession(session.id, {
          status: 'queued',
          deliveryError: `Could not keep all local delivery media: ${error?.message || 'storage error'}`,
        }))
    }
    return session.id
  }, [patchSession, backendHealth])

  const retrySession = useCallback((id) => {
    patchSession(id, {
      status: 'queued', error: null, result: null, delivery: null,
      deliveryError: null, startedAt: null, completedAt: null,
      drill: {
        state: 'idle', maxRounds: 3, challenges: [], coreConceptsCoverage: 0,
        weakAreas: [], coverageStatus: 'developing', rounds: [], finalSummary: null,
        stopReason: '', error: null,
      },
      analysisState: { content: 'queued', audio: 'queued', vision: 'queued' },
    })
  }, [patchSession])

  const removeSession = useCallback((id) => {
    if (inFlightIdRef.current === id) return false
    setSessions((current) => current.filter((session) => session.id !== id))
    setActiveId((currentActiveId) => (currentActiveId === id ? null : currentActiveId))
    deleteSessionAudio(id).catch(() => {})
    deleteSessionVideo(id).catch(() => {})
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
          delivery: null,
          deliveryError: null,
          drill: {
            state: 'idle', maxRounds: 3, challenges: [], coreConceptsCoverage: 0,
            weakAreas: [], coverageStatus: 'developing', rounds: [], finalSummary: null,
            stopReason: '', error: null,
          },
          error: null,
          startedAt: null,
          completedAt: null,
          analysisState: { content: 'queued', audio: 'queued', vision: 'queued' },
          updatedAt: new Date().toISOString(),
        }
      }
      return { ...session, transcript: clean, updatedAt: new Date().toISOString() }
    }))
    return true
  }, [])

  const regenerateDrills = useCallback(async (id) => {
    const session = sessionsRef.current.find((item) => item.id === id)
    if (!session?.result) return false
    patchSession(id, { drill: { ...(session.drill || {}), state: 'generating', error: null } })
    try {
      const generated = await generateDrillChallenges(session, session.result)
      patchSession(id, {
        drill: {
          ...(session.drill || {}),
          state: generated.drill_recommended === false ? 'skipped' : 'ready',
          maxRounds: session.drill?.maxRounds || 3,
          challenges: generated.drill_recommended === false ? [] : (generated.challenges || []),
          coreConceptsCoverage: generated.core_concepts_coverage || session.drill?.coreConceptsCoverage || 0,
          weakAreas: generated.weak_areas || [],
          coverageStatus: generated.coverage_status || 'developing',
          rounds: session.drill?.rounds || [],
          stopReason: generated.skip_reason || '',
          skipReason: generated.skip_reason || '',
          drillRecommended: generated.drill_recommended !== false,
          error: null,
        },
      })
      return true
    } catch (error) {
      patchSession(id, { drill: { ...(session.drill || {}), state: 'error', error: error?.message || 'Could not generate drills.' } })
      return false
    }
  }, [patchSession])

  const submitDrillAnswer = useCallback(async (id, challenge, answer) => {
    const session = sessionsRef.current.find((item) => item.id === id)
    if (!session || !challenge || !answer?.trim()) return false
    patchSession(id, { drill: { ...(session.drill || {}), state: 'evaluating', error: null } })
    try {
      const evaluation = await evaluateDrillRound(session, challenge, answer.trim())
      const current = sessionsRef.current.find((item) => item.id === id) || session
      const priorRounds = current.drill?.rounds || []
      const overallSnapshot = qaOverallSnapshot(current.result, priorRounds, evaluation.overall_score)
      const round = {
        id: `${id}-round-${priorRounds.length + 1}-${Date.now()}`,
        roundNumber: priorRounds.length + 1,
        challenge,
        answer: answer.trim(),
        evaluation,
        ...overallSnapshot,
        completedAt: new Date().toISOString(),
      }
      const finished = Boolean(evaluation.should_stop)
      const nextChallenges = finished
        ? []
        : replaceChallengeOfType(current.drill?.challenges || [], challenge, evaluation.next_challenges || [])
      patchSession(id, {
        drill: {
          ...(current.drill || {}),
          state: finished ? 'complete' : 'ready',
          challenges: nextChallenges,
          coreConceptsCoverage: evaluation.core_concepts_coverage,
          weakAreas: evaluation.remaining_weak_areas || [],
          coverageStatus: evaluation.coverage_status || 'developing',
          rounds: [...priorRounds, round],
          finalSummary: evaluation.final_summary || null,
          stopReason: evaluation.stop_reason || '',
          error: null,
        },
      })
      return true
    } catch (error) {
      const current = sessionsRef.current.find((item) => item.id === id) || session
      patchSession(id, { drill: { ...(current.drill || {}), state: 'ready', error: error?.message || 'Could not evaluate this Q&A answer.' } })
      return false
    }
  }, [patchSession])

  const finishDrills = useCallback(async (id) => {
    const session = sessionsRef.current.find((item) => item.id === id)
    if (!session) return false
    patchSession(id, { drill: { ...(session.drill || {}), state: 'evaluating', error: null } })
    try {
      const result = await finalizeDrillSession(session)
      const current = sessionsRef.current.find((item) => item.id === id) || session
      patchSession(id, {
        drill: {
          ...(current.drill || {}),
          state: 'complete',
          challenges: [],
          coverageStatus: result.coverage_status || current.drill?.coverageStatus || 'developing',
          coreConceptsCoverage: result.core_concepts_coverage ?? current.drill?.coreConceptsCoverage ?? 0,
          finalSummary: result.final_summary,
          stopReason: 'Practice ended by the user.',
          error: null,
        },
      })
      return true
    } catch (error) {
      patchSession(id, { drill: { ...(session.drill || {}), state: 'ready', error: error?.message || 'Could not create the final summary.' } })
      return false
    }
  }, [patchSession])

  const activeSession = useMemo(() => sessions.find((session) => session.id === activeId) ?? null, [sessions, activeId])
  const counts = useMemo(() => ({
    queued: sessions.filter((item) => ['queued', 'preparing'].includes(item.status)).length,
    processing: sessions.filter((item) => item.status === 'processing').length,
    complete: sessions.filter((item) => item.status === 'complete').length,
    error: sessions.filter((item) => item.status === 'error').length,
  }), [sessions])

  return {
    sessions,
    activeSession,
    activeId,
    counts,
    backendHealth,
    localDeliveryEnabled,
    localAudioEnabled,
    localVisionEnabled,
    backendUnreachable,
    localAiOffline,
    uploadLimits,
    refreshHealth,
    addSession,
    setActiveId,
    retrySession,
    removeSession,
    updateTranscript,
    regenerateDrills,
    submitDrillAnswer,
    finishDrills,
    startNewSession: () => setActiveId(null),
  }
}
