import { useEffect, useMemo, useState } from 'react'

export default function TranscriptCard({ session, onUpdateTranscript }) {
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState(session.transcript || '')
  const [copied, setCopied] = useState(false)

  useEffect(() => {
    setDraft(session.transcript || '')
    setEditing(false)
    setCopied(false)
  }, [session.id, session.transcript])

  const wordCount = useMemo(() => {
    const text = (editing ? draft : session.transcript || '').trim()
    return text ? text.split(/\s+/).length : 0
  }, [draft, editing, session.transcript])

  async function copyTranscript() {
    try {
      await navigator.clipboard.writeText(session.transcript || '')
      setCopied(true)
      window.setTimeout(() => setCopied(false), 1300)
    } catch {
      setCopied(false)
    }
  }

  function cancelEdit() {
    setDraft(session.transcript || '')
    setEditing(false)
  }

  function save(reanalyze) {
    const clean = draft.trim()
    if (clean.length < 20) return
    const ok = onUpdateTranscript(session.id, clean, { reanalyze })
    if (ok) setEditing(false)
  }

  const canEdit = session.status !== 'processing'
  const changed = draft.trim() !== (session.transcript || '').trim()
  const valid = draft.trim().length >= 20

  return (
    <section className="transcript-card">
      <div className="section-heading transcript-heading">
        <div>
          <div className="eyebrow">Source</div>
          <h2>Transcript</h2>
        </div>
        <div className="transcript-actions">
          <span className="transcript-count">{wordCount} words</span>
          <button type="button" className="ghost-button" onClick={copyTranscript}>
            {copied ? 'Copied' : 'Copy'}
          </button>
          {!editing && (
            <button
              type="button"
              className="ghost-button"
              disabled={!canEdit}
              onClick={() => setEditing(true)}
              title={canEdit ? 'Edit transcript' : 'Wait until analysis finishes'}
            >
              Edit
            </button>
          )}
        </div>
      </div>

      {editing ? (
        <div className="transcript-editor-wrap">
          <textarea
            className="transcript-editor"
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
            autoFocus
          />
          <div className="transcript-editor-footer">
            <p>
              Editing does not change the current report until you run analysis again.
            </p>
            <div className="transcript-editor-buttons">
              <button type="button" className="ghost-button" onClick={cancelEdit}>Cancel</button>
              <button
                type="button"
                className="ghost-button"
                disabled={!valid || !changed}
                onClick={() => save(false)}
              >
                Save only
              </button>
              <button
                type="button"
                className="primary-button compact-button"
                disabled={!valid || !changed}
                onClick={() => save(true)}
              >
                Save & re-analyze
              </button>
            </div>
          </div>
        </div>
      ) : (
        <p className="transcript-copy">{session.transcript}</p>
      )}

      {session.referenceContent && (
        <details className="reference-details">
          <summary>Reference content</summary>
          <p>{session.referenceContent}</p>
        </details>
      )}
    </section>
  )
}
