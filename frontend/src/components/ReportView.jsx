import ScoreBar from './ScoreBar.jsx'
import PlaceholderModule from './PlaceholderModule.jsx'

const scoreLabels = {
  correctness: 'Correctness',
  completeness: 'Completeness',
  logical_flow: 'Logical flow',
  clarity: 'Clarity',
  examples: 'Examples',
  jumped_steps: 'Step-by-step flow',
  audience_fit: 'Audience fit',
}

function overallScore(scores = {}) {
  const values = Object.values(scores).map(Number).filter(Number.isFinite)
  if (!values.length) return 0
  return Math.round(values.reduce((sum, value) => sum + value, 0) / values.length)
}

function severityClass(severity = '') {
  const normalized = severity.toLowerCase()
  if (normalized.includes('high')) return 'severity-high'
  if (normalized.includes('low')) return 'severity-low'
  return 'severity-medium'
}

export default function ReportView({ result }) {
  const scores = result?.scores || {}
  const issues = Array.isArray(result?.issues) ? result.issues : []
  const priorities = Array.isArray(result?.top_priorities) ? result.top_priorities : []
  const overall = overallScore(scores)

  return (
    <div className="report-stack">
      <section className="report-overview">
        <div className="overall-score">
          <div className="score-ring" style={{ '--score': `${overall * 3.6}deg` }}>
            <div><strong>{overall}</strong><span>/100</span></div>
          </div>
          <div>
            <div className="eyebrow">Content score</div>
            <h2>Your explanation report</h2>
            <p>Generated from the transcript using the content-analysis rubric.</p>
            <span className="provider-tag">{result?.meta?.provider || 'AI'} · {result?.meta?.model || 'content evaluator'}</span>
          </div>
        </div>
        <div className="score-grid">
          {Object.entries(scoreLabels).map(([key, label]) => (
            <ScoreBar key={key} label={label} value={scores[key]} />
          ))}
        </div>
      </section>

      <section className="feedback-card">
        <div className="feedback-marker">AI</div>
        <div>
          <div className="eyebrow">Overall feedback</div>
          <p>{result?.feedback || 'No summary feedback returned.'}</p>
        </div>
      </section>

      <section className="report-section">
        <div className="section-heading">
          <div>
            <div className="eyebrow">Diagnostic feedback</div>
            <h2>What to improve</h2>
          </div>
          <span>{issues.length} issue{issues.length === 1 ? '' : 's'}</span>
        </div>

        {issues.length === 0 ? (
          <div className="clean-card">No major issues were detected in this explanation.</div>
        ) : (
          <div className="issue-list">
            {issues.map((issue, index) => (
              <article className="issue-card" key={`${issue.category}-${index}`}>
                <div className="issue-topline">
                  <span className={`severity ${severityClass(issue.severity)}`}>{issue.severity || 'medium'}</span>
                  <span className="issue-category">{scoreLabels[issue.category] || issue.category || 'content'}</span>
                  {Number.isInteger(issue.sentence_index) && <span className="sentence-chip">Sentence {issue.sentence_index}</span>}
                </div>
                {issue.sentence && <blockquote>“{issue.sentence}”</blockquote>}
                <div className="issue-columns">
                  <div><small>Problem</small><p>{issue.problem}</p></div>
                  <div><small>Suggestion</small><p>{issue.suggestion}</p></div>
                </div>
              </article>
            ))}
          </div>
        )}
      </section>

      <section className="priority-section">
        <div>
          <div className="eyebrow">Next attempt</div>
          <h2>Top priorities</h2>
        </div>
        <div className="priority-list">
          {priorities.length ? priorities.map((priority, index) => (
            <div className="priority-item" key={`${priority}-${index}`}>
              <span>{String(index + 1).padStart(2, '0')}</span>
              <p>{priority}</p>
            </div>
          )) : <p className="muted">No priorities returned.</p>}
        </div>
      </section>

      {result?.revision_guidance && (
        <section className="feedback-card revision-card">
          <div className="feedback-marker">↻</div>
          <div>
            <div className="eyebrow">Revision guidance</div>
            <p>{result.revision_guidance}</p>
          </div>
        </section>
      )}

      <section className="future-modules">
        <PlaceholderModule
          eyebrow="Phase 2"
          title="Delivery analysis"
          description="Speaking pace, pauses, filler words, volume, rhythm and confidence will plug into this reserved module."
          icon="◉"
        />
        <PlaceholderModule
          eyebrow="Phase 3"
          title="Visual communication"
          description="Eye contact, head direction, posture and gestures will plug into this reserved computer-vision module."
          icon="◇"
        />
      </section>
    </div>
  )
}
