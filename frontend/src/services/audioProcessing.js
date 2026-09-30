function writeString(view, offset, text) {
  for (let i = 0; i < text.length; i += 1) view.setUint8(offset + i, text.charCodeAt(i))
}

function encodeWav(samples, sampleRate) {
  const buffer = new ArrayBuffer(44 + samples.length * 2)
  const view = new DataView(buffer)
  writeString(view, 0, 'RIFF')
  view.setUint32(4, 36 + samples.length * 2, true)
  writeString(view, 8, 'WAVE')
  writeString(view, 12, 'fmt ')
  view.setUint32(16, 16, true)
  view.setUint16(20, 1, true)
  view.setUint16(22, 1, true)
  view.setUint32(24, sampleRate, true)
  view.setUint32(28, sampleRate * 2, true)
  view.setUint16(32, 2, true)
  view.setUint16(34, 16, true)
  writeString(view, 36, 'data')
  view.setUint32(40, samples.length * 2, true)
  let offset = 44
  for (let i = 0; i < samples.length; i += 1) {
    const value = Math.max(-1, Math.min(1, samples[i]))
    view.setInt16(offset, value < 0 ? value * 0x8000 : value * 0x7fff, true)
    offset += 2
  }
  return new Blob([buffer], { type: 'audio/wav' })
}

export async function compressedAudioToWav(blob, targetRate = 16000) {
  const AudioContext = globalThis.AudioContext || globalThis.webkitAudioContext
  const OfflineAudioContext = globalThis.OfflineAudioContext || globalThis.webkitOfflineAudioContext
  if (!AudioContext || !OfflineAudioContext) throw new Error('This browser cannot prepare audio for local delivery analysis.')

  const context = new AudioContext()
  try {
    const input = await context.decodeAudioData(await blob.arrayBuffer())
    const frames = Math.max(1, Math.ceil(input.duration * targetRate))
    const offline = new OfflineAudioContext(1, frames, targetRate)
    const source = offline.createBufferSource()
    source.buffer = input
    source.connect(offline.destination)
    source.start(0)
    const rendered = await offline.startRendering()
    return encodeWav(rendered.getChannelData(0), targetRate)
  } finally {
    await context.close().catch(() => {})
  }
}

// Transcription has to be sent in pieces once a recording gets long.
//
// Two ceilings sit on the path and neither can be raised. A serverless function
// refuses a request body over 4.5 MB before any code runs, and a Cloudflare
// Tunnel cuts the connection when the origin takes longer than about 100
// seconds to answer - Whisper on five minutes of speech takes longer than that.
// A five-minute recording is 9.2 MB of 16 kHz mono WAV, so it failed both ways:
// "Failed to fetch" through the serverless backend, 524 through the tunnel.
//
// A minute per piece sits comfortably under both: 1.9 MB, and a few seconds of
// model time.
export const TRANSCRIPTION_CHUNK_SECONDS = 60

/** Read a 16-bit PCM mono WAV this app produced. Returns null for anything else. */
function readPcmWav(buffer) {
  const view = new DataView(buffer)
  const tag = (offset) => String.fromCharCode(
    view.getUint8(offset), view.getUint8(offset + 1), view.getUint8(offset + 2), view.getUint8(offset + 3),
  )
  if (buffer.byteLength < 44 || tag(0) !== 'RIFF' || tag(8) !== 'WAVE') return null

  let offset = 12
  let format = null
  let dataStart = 0
  let dataLength = 0
  while (offset + 8 <= buffer.byteLength) {
    const id = tag(offset)
    const size = view.getUint32(offset + 4, true)
    const body = offset + 8
    if (id === 'fmt ') {
      format = {
        audioFormat: view.getUint16(body, true),
        channels: view.getUint16(body + 2, true),
        sampleRate: view.getUint32(body + 4, true),
        bitsPerSample: view.getUint16(body + 14, true),
      }
    } else if (id === 'data') {
      dataStart = body
      dataLength = Math.min(size, buffer.byteLength - body)
    }
    offset = body + size + (size % 2)
  }
  if (!format || !dataStart) return null
  if (format.audioFormat !== 1 || format.channels !== 1 || format.bitsPerSample !== 16) return null
  return { ...format, samples: new Int16Array(buffer, dataStart, Math.floor(dataLength / 2)) }
}

function wavFromPcm(samples, sampleRate) {
  const buffer = new ArrayBuffer(44 + samples.length * 2)
  const view = new DataView(buffer)
  writeString(view, 0, 'RIFF')
  view.setUint32(4, 36 + samples.length * 2, true)
  writeString(view, 8, 'WAVE')
  writeString(view, 12, 'fmt ')
  view.setUint32(16, 16, true)
  view.setUint16(20, 1, true)
  view.setUint16(22, 1, true)
  view.setUint32(24, sampleRate, true)
  view.setUint32(28, sampleRate * 2, true)
  view.setUint16(32, 2, true)
  view.setUint16(34, 16, true)
  writeString(view, 36, 'data')
  view.setUint32(40, samples.length * 2, true)
  new Int16Array(buffer, 44).set(samples)
  return new Blob([buffer], { type: 'audio/wav' })
}

/** The quietest 20 ms inside a window, so a cut lands between words.
 *
 * Splitting on a fixed clock would cut mid-word and cost that word from both
 * pieces. The gap between sentences is usually the quietest point nearby.
 */
function quietestOffset(samples, from, to) {
  const frame = Math.max(1, Math.floor((to - from) / 128))
  let bestOffset = Math.floor((from + to) / 2)
  let bestEnergy = Infinity
  for (let start = from; start + frame <= to; start += frame) {
    let energy = 0
    for (let i = start; i < start + frame; i += 4) energy += Math.abs(samples[i])
    if (energy < bestEnergy) {
      bestEnergy = energy
      bestOffset = start + Math.floor(frame / 2)
    }
  }
  return bestOffset
}

/** Split a WAV into transcription-sized pieces.
 *
 * Returns the blob untouched when it is short enough, or when it is not the
 * 16-bit mono PCM this app produces - a compressed recording from the live
 * microphone cannot be cut without decoding it, and is small anyway.
 */
export async function splitWavForTranscription(blob, maxSeconds = TRANSCRIPTION_CHUNK_SECONDS) {
  if (!blob || !/wav/i.test(blob.type || '')) return [blob]
  const parsed = readPcmWav(await blob.arrayBuffer())
  if (!parsed) return [blob]

  const { samples, sampleRate } = parsed
  const perChunk = Math.floor(maxSeconds * sampleRate)
  if (samples.length <= perChunk) return [blob]

  // Look for the cut within the last 10% of each piece, so a piece never grows
  // past the ceiling that made splitting necessary.
  const search = Math.floor(perChunk * 0.1)
  const pieces = []
  let start = 0
  while (start < samples.length) {
    const nominal = start + perChunk
    if (nominal >= samples.length) {
      pieces.push(wavFromPcm(samples.subarray(start), sampleRate))
      break
    }
    const cut = quietestOffset(samples, nominal - search, nominal)
    pieces.push(wavFromPcm(samples.subarray(start, cut), sampleRate))
    start = cut
  }
  return pieces
}
