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
