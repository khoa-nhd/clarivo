// Where the Voice + Visual backend lives, decided when the page runs rather
// than when it was built.
//
// `VITE_LOCAL_AI_BASE_URL` is substituted by Vite at build time and frozen into
// the bundle, so changing it means a new Vercel deployment. That does not match
// how the backend is actually published: a Cloudflare quick tunnel invents a
// fresh hostname every time it starts, so the deployed site pointed at a dead
// address after each restart. Worse, when the variable was never set, the
// voice/visual calls fell back to the serverless backend, which has no OpenVINO
// and no model weights - so visual analysis reported unavailable for every
// visitor, while the owner's own machine appeared to work because they were
// testing against localhost.
//
// The address is now resolved in this order, highest first:
//
//   1. `?ai=<url>` in the address bar - what a shared link carries.
//   2. `localStorage` - what such a link left behind, or what someone typed
//      into the in-app field.
//   3. `VITE_LOCAL_AI_BASE_URL` - the build-time value. Unchanged behaviour,
//      so an existing deployment that sets it keeps working exactly as before.
//
// Nothing here touches the main backend (`VITE_API_BASE_URL`): content
// analysis, transcription and the Q&A drills stay on the always-on serverless
// deployment regardless.

const STORAGE_KEY = 'clarivo.localAiBaseUrl'
const QUERY_PARAM = 'ai'

/** The value compiled into the bundle. Empty when it was never configured. */
export const BUILD_TIME_LOCAL_AI_BASE = String(import.meta.env.VITE_LOCAL_AI_BASE_URL || '')
  .trim()
  .replace(/\/+$/, '')

const listeners = new Set()

const NOT_AN_ADDRESS =
  'That does not look like an address. Expected something like https://abc-def.trycloudflare.com'

// Hostname per RFC 1123: dot-separated labels of letters, digits and hyphens,
// never starting or ending with a hyphen.
const HOSTNAME = /^[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)*$/i
const IPV4 = /^\d{1,3}(\.\d{1,3}){3}$/
const LOOPBACK = /^(localhost|127\.0\.0\.1|\[::1\])$/i
// Addresses that are never reached over TLS in practice: this machine, and the
// local network. Typing `127.0.0.1:8000` should not silently become https.
const PRIVATE_HOST = /^(localhost|127\.\d+\.\d+\.\d+|10\.\d+\.\d+\.\d+|192\.168\.\d+\.\d+|172\.(1[6-9]|2\d|3[01])\.\d+\.\d+|\[::1\])$/i

/** Reduce user input to a usable origin, or throw explaining why it is not one.
 *
 * Accepts a bare hostname so that pasting `abc-def.trycloudflare.com` works;
 * cloudflared prints the full URL, but people copy the visible part.
 *
 * The hostname is checked explicitly rather than left to `new URL`, which is
 * far more permissive than it looks: `new URL('https://not a url at all')`
 * parses happily, percent-encoding the spaces into the host. That was accepted
 * here at first, and the only symptom was voice/visual silently reporting
 * offline - the error belongs at the point the address is typed.
 */
export function normalizeBaseUrl(raw) {
  const text = String(raw ?? '').trim()
  if (!text) return ''
  if (/\s/.test(text)) throw new Error(NOT_AN_ADDRESS)

  const hasScheme = /^[a-z][a-z0-9+.-]*:\/\//i.test(text)
  let parsed
  try {
    parsed = new URL(hasScheme ? text : `https://${text}`)
    // A tunnel hostname is https, so that is the right default - but this
    // machine and the local network are not, and assuming https there turns a
    // correct address into an unreachable one.
    if (!hasScheme && PRIVATE_HOST.test(parsed.hostname)) parsed = new URL(`http://${text}`)
  } catch {
    throw new Error(NOT_AN_ADDRESS)
  }
  if (parsed.protocol !== 'https:' && parsed.protocol !== 'http:') {
    throw new Error('The address must start with https://')
  }
  const host = parsed.hostname
  const isIpLiteral = IPV4.test(host) || host.startsWith('[')
  if (!host || (!isIpLiteral && !HOSTNAME.test(host))) throw new Error(NOT_AN_ADDRESS)
  // A single label is never a public address; it is a typo, or half of one
  // pasted by accident. Loopback is the one name that legitimately has no dot.
  if (!isIpLiteral && !host.includes('.') && !LOOPBACK.test(host)) throw new Error(NOT_AN_ADDRESS)
  // A page served over https cannot call a plain http address: the browser
  // blocks it as mixed content and the request never leaves. Say so here
  // rather than letting it fail later as an unexplained network error.
  const pageIsSecure = typeof window !== 'undefined' && window.location?.protocol === 'https:'
  const targetIsLoopback = LOOPBACK.test(host)
  if (pageIsSecure && parsed.protocol === 'http:' && !targetIsLoopback) {
    throw new Error('This page is served over https, so the address must use https:// too.')
  }

  // Keep only the origin. The endpoint paths are appended by the API layer, and
  // a trailing path here would produce /some/path/api/health.
  return `${parsed.protocol}//${parsed.host}`
}

function readStored() {
  try {
    return String(window.localStorage.getItem(STORAGE_KEY) || '').trim()
  } catch {
    // Private browsing, or storage disabled. Treat as "nothing stored".
    return ''
  }
}

function writeStored(value) {
  try {
    if (value) window.localStorage.setItem(STORAGE_KEY, value)
    else window.localStorage.removeItem(STORAGE_KEY)
  } catch {
    // Not fatal: the address still applies for this page load.
  }
}

/** The runtime override in effect, or '' when none is set. */
export function localAiOverride() {
  if (typeof window === 'undefined') return ''
  const stored = readStored()
  if (!stored) return ''
  try {
    return normalizeBaseUrl(stored)
  } catch {
    // A malformed value would otherwise poison every later request.
    writeStored('')
    return ''
  }
}

/** The address voice/visual requests should go to; '' means "not configured". */
export function resolveLocalAiBase() {
  return localAiOverride() || BUILD_TIME_LOCAL_AI_BASE
}

function notify() {
  for (const listener of listeners) {
    try {
      listener(resolveLocalAiBase())
    } catch {
      // One bad subscriber must not stop the others being told.
    }
  }
}

/** Store a new address. Pass '' to fall back to the build-time value. */
export function setLocalAiOverride(raw) {
  const normalized = normalizeBaseUrl(raw)
  writeStored(normalized)
  notify()
  return normalized
}

export function clearLocalAiOverride() {
  writeStored('')
  notify()
}

export function subscribeLocalAi(listener) {
  listeners.add(listener)
  return () => listeners.delete(listener)
}

/** Whether the address in effect came from a link or the in-app field. */
export function localAiIsOverridden() {
  return localAiOverride().length > 0
}

/** Apply `?ai=` from the address bar, then take it back out of the URL.
 *
 * Removing it matters: left in place it would win over anything typed into the
 * in-app field on the next reload, so a stale shared link could never be
 * corrected from inside the app. `?ai=` with an empty value clears the stored
 * address, which is the documented way to reset a browser that has a dead one.
 */
let linkResult = null

/** What `consumeAddressFromUrl` did, for UI that wants to report it. */
export function getLinkAddressResult() {
  return linkResult
}

export function consumeAddressFromUrl() {
  if (typeof window === 'undefined' || !window.location?.search) return null
  const params = new URLSearchParams(window.location.search)
  if (!params.has(QUERY_PARAM)) return null

  const requested = params.get(QUERY_PARAM) || ''
  let applied = null
  let failure = null
  try {
    applied = requested.trim() ? setLocalAiOverride(requested) : (clearLocalAiOverride(), '')
  } catch (error) {
    failure = error instanceof Error ? error.message : String(error)
  }

  params.delete(QUERY_PARAM)
  const query = params.toString()
  const next = `${window.location.pathname}${query ? `?${query}` : ''}${window.location.hash}`
  try {
    window.history.replaceState(null, '', next)
  } catch {
    // Not worth failing a page load over a cosmetic URL change.
  }
  linkResult = { requested: requested.trim(), applied, failure }
  return linkResult
}
