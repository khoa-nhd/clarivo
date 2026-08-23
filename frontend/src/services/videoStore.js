const DB_NAME = 'clarivo.media.v1'
const STORE_NAME = 'videos'
const DB_VERSION = 2

function openDb() {
  return new Promise((resolve, reject) => {
    if (!('indexedDB' in globalThis)) {
      reject(new Error('This browser does not support local video storage.'))
      return
    }
    const request = indexedDB.open(DB_NAME, DB_VERSION)
    request.onupgradeneeded = () => {
      const db = request.result
      if (!db.objectStoreNames.contains('audio')) db.createObjectStore('audio', { keyPath: 'sessionId' })
      if (!db.objectStoreNames.contains(STORE_NAME)) db.createObjectStore(STORE_NAME, { keyPath: 'sessionId' })
    }
    request.onsuccess = () => resolve(request.result)
    request.onerror = () => reject(request.error || new Error('Could not open local video storage.'))
  })
}

export async function saveSessionVideo(sessionId, blob, metadata = {}) {
  if (!blob || !sessionId) return false
  const db = await openDb()
  return new Promise((resolve, reject) => {
    const tx = db.transaction(STORE_NAME, 'readwrite')
    tx.objectStore(STORE_NAME).put({ sessionId, blob, metadata, savedAt: new Date().toISOString() })
    tx.oncomplete = () => { db.close(); resolve(true) }
    tx.onerror = () => { const error = tx.error || new Error('Could not save the camera recording.'); db.close(); reject(error) }
  })
}

export async function getSessionVideo(sessionId) {
  const db = await openDb()
  return new Promise((resolve, reject) => {
    const tx = db.transaction(STORE_NAME, 'readonly')
    const request = tx.objectStore(STORE_NAME).get(sessionId)
    request.onsuccess = () => { db.close(); resolve(request.result || null) }
    request.onerror = () => { const error = request.error || new Error('Could not read the camera recording.'); db.close(); reject(error) }
  })
}

export async function deleteSessionVideo(sessionId) {
  if (!sessionId || !('indexedDB' in globalThis)) return false
  const db = await openDb()
  return new Promise((resolve, reject) => {
    const tx = db.transaction(STORE_NAME, 'readwrite')
    tx.objectStore(STORE_NAME).delete(sessionId)
    tx.oncomplete = () => { db.close(); resolve(true) }
    tx.onerror = () => { const error = tx.error || new Error('Could not delete the camera recording.'); db.close(); reject(error) }
  })
}
