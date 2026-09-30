import { useEffect, useRef, useState } from 'react'

/** Connect Voice + Visual analysis to a backend, without rebuilding the site.
 *
 * Those two features need OpenVINO and model weights, which the serverless
 * deployment cannot carry, so they are served by a machine reached over a
 * tunnel. A quick tunnel's hostname changes every time it starts, so the
 * address has to be something a visitor can be handed - normally in the link
 * (`?ai=...`), and through this field when the link they have is out of date.
 */
export default function LocalAiAddress({
  baseUrl = '',
  fromLink = false,
  linkError = '',
  offline = false,
  audioReady = false,
  visionReady = false,
  onApply,
  onRefresh,
}) {
  const [open, setOpen] = useState(false)
  const [draft, setDraft] = useState(baseUrl)
  const [error, setError] = useState(linkError)
  const [saved, setSaved] = useState(false)
  const inputRef = useRef(null)

  // Keep the field showing the address actually in use while it is closed; do
  // not overwrite something half-typed.
  useEffect(() => { if (!open) setDraft(baseUrl) }, [baseUrl, open])
  useEffect(() => { if (open) inputRef.current?.focus() }, [open])

  // A link that carried a malformed address is worth opening the panel for:
  // the visitor cannot fix what they cannot see.
  useEffect(() => { if (linkError) { setError(linkError); setOpen(true) } }, [linkError])

  // Report what actually works, not what is configured. With no address set
  // the calls fall back to the main backend, and in local development that
  // backend is the full OpenVINO one - saying "not connected" there would be
  // plainly wrong. "Not connected" is only for the case where nothing serves
  // these two features and no address has been offered.
  const state = audioReady && visionReady
    ? 'ready'
    : audioReady || visionReady
      ? 'partial'
      : (baseUrl || offline) ? 'offline' : 'unset'
  const label = {
    unset: 'Voice + Visual: not connected',
    offline: 'Voice + Visual: offline',
    partial: audioReady ? 'Voice ready · Visual off' : 'Visual ready · Voice off',
    ready: 'Voice + Visual: ready',
  }[state]
  const shortLabel = {
    unset: 'AI: off',
    offline: 'AI: offline',
    partial: audioReady ? 'Visual off' : 'Voice off',
    ready: 'AI: on',
  }[state]

  function handleSubmit(event) {
    event.preventDefault()
    setError('')
    setSaved(false)
    try {
      onApply?.(draft)
      setSaved(true)
      setOpen(false)
    } catch (applyError) {
      setError(applyError?.message || 'That address could not be used.')
    }
  }

  return (
    <div className="ai-address">
      <button
        type="button"
        className={`ai-address-chip ai-address-${state}`}
        onClick={() => setOpen((value) => !value)}
        aria-expanded={open}
        aria-label={`${label}. Change the address.`}
        title={label}
      >
        <span className="ai-address-dot" aria-hidden="true" />
        {/* Two labels rather than one hidden below a breakpoint: a bare
            coloured dot tells a phone visitor nothing, and this is the control
            they need when the link they were sent has gone stale. */}
        <span className="ai-address-long">{label}</span>
        <span className="ai-address-short">{shortLabel}</span>
      </button>

      {open && (
        <form className="ai-address-panel" onSubmit={handleSubmit}>
          <p className="ai-address-help">
            Voice and Visual analysis run on a machine reached over a tunnel. Paste the
            address the organiser gave you — it looks like
            {' '}<code>https://something.trycloudflare.com</code>.
          </p>
          <input
            ref={inputRef}
            type="text"
            value={draft}
            spellCheck="false"
            autoComplete="off"
            placeholder="https://abc-def-ghi.trycloudflare.com"
            onChange={(event) => { setDraft(event.target.value); setError(''); setSaved(false) }}
          />
          {error && <p className="ai-address-error">{error}</p>}
          {saved && !error && <p className="ai-address-ok">Saved. Checking the connection…</p>}
          <div className="ai-address-actions">
            <button type="submit" className="ai-address-save">Connect</button>
            <button type="button" onClick={() => { onRefresh?.(); setOpen(false) }}>Check again</button>
            {fromLink && (
              <button
                type="button"
                className="ai-address-reset"
                onClick={() => { onApply?.(''); setDraft(''); setError(''); setOpen(false) }}
              >
                Reset
              </button>
            )}
          </div>
          <p className="ai-address-note">
            Content analysis and the Q&amp;A drills do not use this address and keep working either way.
          </p>
        </form>
      )}
    </div>
  )
}
