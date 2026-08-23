import { useEffect, useMemo, useState } from 'react'
import DrillRecorder from './DrillRecorder.jsx'

const qaLabels = {
  accuracy: 'Accuracy',
  directness: 'Directness',
  consistency: 'Internal consistency',
  relevance: 'Relevance',
  audience_fit: 'Audience fit',
}

const typeMeta = {
  audience: { letter: 'A', title: 'Audience question', subtitle: 'A realistic listener question' },
  deep_dive: { letter: 'B', title: 'Deep dive', subtitle: 'Explain one point in more depth' },
  broaden: { letter: 'C', title: 'Broaden', subtitle: 'Connect to one related idea' },
}

function ScoreLine({ label, value }) {
  const safe = Math.max(0, Math.min(100, Number(value) || 0))
  return (
    <div className="qa-score-line">
      <div><span>{label}</span><strong>{Math.round(safe)}</strong></div>
      <div className="qa-score-track"><span style={{ width: `${safe}%` }} /></div>
    </div>
  )
}

function SummaryList({ title, values, empty }) {
  return (
    <div className="learning-summary-list">
      <span>{title}</span>
      {values?.length ? <ul>{values.map((item, index) => <li key={`${title}-${index}`}>{item}</li>)}</ul> : <p>{empty}</p>}
    </div>
  )
}

export default function InteractiveDrill({ session, onAnswer, onRegenerate, onFinalize }) {
  const drill = session.drill || {}
  const challenges = Array.isArray(drill.challenges) ? drill.challenges : []
  const rounds = Array.isArray(drill.rounds) ? drill.rounds : []
  const [selectedId, setSelectedId] = useState(challenges[0]?.id || '')
  const [selectedType, setSelectedType] = useState(challenges[0]?.type || 'audience')

  const selected = useMemo(
    () => challenges.find((challenge) => challenge.id === selectedId) || challenges[0] || null,
    [challenges, selectedId],
  )

  useEffect(() => {
    if (!challenges.length) return
    if (challenges.some((challenge) => challenge.id === selectedId)) return
    const sameType = challenges.find((challenge) => challenge.type === selectedType)
    setSelectedId((sameType || challenges[0]).id)
  }, [challenges, selectedId, selectedType])

  const state = drill.state || 'idle'
  const coverage = Number.isFinite(Number(drill.coreConceptsCoverage)) ? Math.round(Number(drill.coreConceptsCoverage)) : 0
  const maxRounds = drill.maxRounds || 3
  const finished = state === 'complete' || Boolean(drill.finalSummary)
  const latestRound = rounds[rounds.length - 1] || null

  if (!session.result) return null

  return (
    <section className="interactive-drill-section">
      <div className="interactive-drill-heading">
        <div>
          <div className="eyebrow">Understanding drill</div>
          <h2>Follow-up Q&A</h2>
          <p>Answer focused questions to test your understanding.</p>
        </div>
        <div className="coverage-badge">
          <span>Coverage</span>
          <strong>{coverage}%</strong>
          <small>{drill.coverageStatus === 'satisfactory' ? 'Satisfactory' : 'Developing'}</small>
        </div>
      </div>

      <div className="coverage-track"><span style={{ width: `${coverage}%` }} /></div>
      {state !== 'skipped' && (
        <div className="drill-status-row">
          <span>Round {Math.min(rounds.length + (finished ? 0 : 1), maxRounds)} of {maxRounds}</span>
          <span>{drill.weakAreas?.length ? `${drill.weakAreas.length} weak area${drill.weakAreas.length === 1 ? '' : 's'} remaining` : 'No open weak areas'}</span>
        </div>
      )}

      {latestRound?.overallAfterQA != null && (
        <div className="qa-current-overall">
          <div><span>Main overall</span><strong>{latestRound.mainOverall}</strong></div>
          <div className={`qa-impact ${latestRound.overallDelta >= 0 ? 'positive' : 'negative'}`}><span>Q&A impact</span><strong>{latestRound.overallDelta >= 0 ? '+' : ''}{latestRound.overallDelta}</strong></div>
          <div className="qa-after-score"><span>Overall after Q&A</span><strong>{latestRound.overallAfterQA}</strong></div>
        </div>
      )}

      {state === 'skipped' && (
        <div className="drill-skip-card">
          <div className="drill-skip-icon">↻</div>
          <div>
            <div className="eyebrow">Revise before Q&A</div>
            <h3>Revise the presentation first</h3>
            <p>{drill.skipReason || drill.stopReason || 'There are too many major content gaps for useful follow-up questions.'}</p>
            
          </div>
        </div>
      )}

      {state === 'generating' && (
        <div className="drill-loading-card">
          <div className="loader-orbit"><span /></div>
          <div><strong>Creating follow-up questions…</strong></div>
        </div>
      )}

      {state === 'error' && !challenges.length && (
        <div className="drill-error-card">
          <div><strong>Could not create questions.</strong><p>{drill.error || 'Try again.'}</p></div>
          <button type="button" className="ghost-button" onClick={() => onRegenerate(session.id)}>Generate again</button>
        </div>
      )}

      {state === 'idle' && !challenges.length && (
        <div className="drill-error-card drill-start-card">
          <div><strong>No follow-up questions yet.</strong></div>
          <button type="button" className="primary-button compact-button" onClick={() => onRegenerate(session.id)}>Generate questions</button>
        </div>
      )}

      {drill.error && challenges.length > 0 && <div className="drill-inline-error">{drill.error}</div>}

      {!finished && challenges.length > 0 && (
        <>
          <div className="challenge-grid">
            {challenges.map((challenge) => {
              const meta = typeMeta[challenge.type] || { letter: '?', title: challenge.label, subtitle: challenge.focus }
              const active = selected?.id === challenge.id
              return (
                <button
                  type="button"
                  key={challenge.id}
                  className={`challenge-card ${active ? 'active' : ''}`}
                  onClick={() => { setSelectedId(challenge.id); setSelectedType(challenge.type) }}
                  disabled={state === 'evaluating'}
                >
                  <div className="challenge-letter">{meta.letter}</div>
                  <div className="challenge-card-copy">
                    <span>{meta.title}</span>
                    <strong>{challenge.prompt}</strong>
                    <small>{meta.subtitle}</small>
                  </div>
                  <i>{active ? 'Selected' : 'Choose'}</i>
                </button>
              )
            })}
          </div>

          {selected && (
            <div className="selected-challenge-panel">
              <div className="selected-challenge-copy">
                <span className="delivery-panel-tag">Selected challenge · {typeMeta[selected.type]?.letter || ''}</span>
                <h3>{selected.prompt}</h3>
                
              </div>
              {state === 'evaluating' ? (
                <div className="drill-loading-card inline">
                  <div className="loader-orbit"><span /></div>
                  <div><strong>Scoring answer…</strong></div>
                </div>
              ) : (
                <DrillRecorder
                  key={`${session.id}-${selected.id}-${rounds.length}`}
                  resetKey={`${selected.id}-${rounds.length}`}
                  topic={session.topic}
                  disabled={state === 'evaluating'}
                  onSubmit={(answer) => onAnswer(session.id, selected, answer)}
                />
              )}
            </div>
          )}

          <div className="drill-manual-stop">
            <div><strong>Done?</strong></div>
            <button type="button" className="ghost-button" disabled={state === 'evaluating'} onClick={() => onFinalize(session.id)}>Finish practice</button>
          </div>
        </>
      )}

      {rounds.length > 0 && (
        <div className="qa-history-block">
          <div className="qa-history-heading"><div><div className="eyebrow">History</div><h3>Q&A rounds</h3></div><span>{rounds.length} completed</span></div>
          <div className="qa-history-list">
            {[...rounds].reverse().map((round) => (
              <details className="qa-round-card" key={round.id || round.roundNumber} open={round.roundNumber === rounds.length}>
                <summary>
                  <div className="qa-round-index">{String(round.roundNumber).padStart(2, '0')}</div>
                  <div><span>{typeMeta[round.challenge?.type]?.title || 'Q&A challenge'}</span><strong>{round.challenge?.prompt}</strong></div>
                  <div className="qa-round-score">{Math.round(round.evaluation?.overall_score || 0)}</div>
                </summary>
                <div className="qa-round-body">
                  <div className="qa-answer-box"><span>Your answer</span><p>{round.answer}</p></div>
                  <div className="qa-score-grid">
                    {Object.entries(qaLabels).map(([key, label]) => <ScoreLine key={key} label={label} value={round.evaluation?.scores?.[key]} />)}
                  </div>
                  <div className="qa-round-feedback">
                    <div><span>What worked</span><p>{round.evaluation?.strength || '—'}</p></div>
                    <div><span>Improve next</span><p>{round.evaluation?.improvement || round.evaluation?.feedback || '—'}</p></div>
                  </div>
                  {round.overallAfterQA != null && (
                    <div className="qa-overall-after">
                      <div><span>Main overall</span><strong>{round.mainOverall}</strong></div>
                      <div className={`qa-overall-delta ${round.overallDelta >= 0 ? 'positive' : 'negative'}`}><span>Q&A adjustment</span><strong>{round.overallDelta >= 0 ? '+' : ''}{round.overallDelta}</strong></div>
                      <div className="qa-overall-result"><span>Overall after Q&A</span><strong>{round.overallAfterQA}</strong></div>

                    </div>
                  )}
                </div>
              </details>
            ))}
          </div>
        </div>
      )}

      {finished && drill.finalSummary && (
        <div className="final-learning-summary">
          <div className="final-learning-hero">
            <div>
              <div className="eyebrow">Final summary</div>
              <h2>{drill.coverageStatus === 'satisfactory' ? 'Good coverage' : 'Review remaining gaps'}</h2>
              <p>{drill.stopReason || 'Practice complete.'}</p>
            </div>
            <div className="final-coverage-score"><strong>{coverage}</strong><span>% coverage</span></div>
          </div>
          <div className="final-learning-grid">
            <SummaryList title="Key strengths" values={drill.finalSummary.key_strengths} empty="No clear strength was recorded." />
            <SummaryList title="Remaining gaps" values={drill.finalSummary.remaining_gaps} empty="No unresolved gap was listed." />
            <div className="learning-summary-list wide"><span>Q&A progress</span><p>{drill.finalSummary.qna_progress || 'No Q&A progress note.'}</p></div>
            <SummaryList title="Next steps" values={drill.finalSummary.next_steps} empty="Try another topic from the library." />
          </div>
        </div>
      )}
    </section>
  )
}
