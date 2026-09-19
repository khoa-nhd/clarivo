import ScoreBar from './ScoreBar.jsx'
import DeliverySummary from './DeliverySummary.jsx'

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

const referenceGroups = [
  ['contradicted_by_reference', 'Contradicts the reference', 'reference-bad'],
  ['missing_from_transcript', 'In the reference but not covered', 'reference-warn'],
  ['unsupported_by_reference', 'Said, but the reference does not confirm it', 'reference-warn'],
  ['supported_claims', 'Backed by the reference', 'reference-good'],
]

function ReferenceCheckCard({ check }) {
  if (!check || check.reference_available === false) return null
  const groups = referenceGroups
    .map(([key, title, tone]) => [title, tone, Array.isArray(check[key]) ? check[key].filter(Boolean) : []])
    .filter(([, , items]) => items.length > 0)
  if (!groups.length) return null

  return (
    <section className="report-section reference-check">
      <div className="section-heading">
        <div><div className="eyebrow">Grounding</div><h2>Checked against your reference</h2></div>
      </div>
      <div className="reference-groups">
        {groups.map(([title, tone, items]) => (
          <div className={`reference-group ${tone}`} key={title}>
            <small>{title}</small>
            <ul>{items.map((item, index) => <li key={index}>{item}</li>)}</ul>
          </div>
        ))}
      </div>
    </section>
  )
}

export default function ReportView({ result, delivery, deliveryError }) {
  const scores = result?.scores || {}
  const issues = Array.isArray(result?.issues) ? result.issues : []
  const priorities = Array.isArray(result?.top_priorities) ? result.top_priorities : []
  const overall = overallScore(scores)
  // Optional: only present when the model returned per-dimension justification.
  const evidence = result?.dimension_evidence || {}
  const referenceCheck = result?.reference_check || null

  return (
    <div className="report-stack">
      <section className="report-overview">
        <div className="overall-score">
          <div className="score-ring" style={{ '--score': `${overall * 3.6}deg` }}>
            <div><strong>{overall}</strong><span>/100</span></div>
          </div>
          <div>
            <div className="eyebrow">Content score</div>
            <h2>Content report</h2>
            

          </div>
        </div>
        <div className="score-grid">
          {Object.entries(scoreLabels).map(([key, label]) => (
            <ScoreBar key={key} label={label} value={scores[key]} evidence={evidence[key]} />
          ))}
        </div>
      </section>

      {Object.keys(evidence).length > 0 && (
        <p className="muted evidence-hint">Tap any score to see the transcript evidence behind it.</p>
      )}

      <ReferenceCheckCard check={referenceCheck} />

      <DeliverySummary delivery={delivery} error={deliveryError} />

      <section className="feedback-card">
        <div className="feedback-marker">AI</div>
        <div>
          <div className="eyebrow">Summary</div>
          <p>{result?.feedback || 'No summary feedback returned.'}</p>
        </div>
      </section>

      <section className="report-section">
        <div className="section-heading">
          <div><div className="eyebrow">Feedback</div><h2>What to improve</h2></div>
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
        <div><div className="eyebrow">Next attempt</div><h2>Priorities</h2></div>
        <div className="priority-list">
          {priorities.length ? priorities.map((priority, index) => (
            <div className="priority-item" key={`${priority}-${index}`}><span>{String(index + 1).padStart(2, '0')}</span><p>{priority}</p></div>
          )) : <p className="muted">No priorities returned.</p>}
        </div>
      </section>

      {result?.revision_guidance && (
        <section className="feedback-card revision-card">
          <div className="feedback-marker">↻</div>
          <div><div className="eyebrow">Try next</div><p>{result.revision_guidance}</p></div>
        </section>
      )}
    </div>
  )
}
