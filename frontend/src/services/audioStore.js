// Keep the existing DB name so recordings from the previous UI build remain available.
const DB_NAME = 'explaincoach-media'
const DB_VERSION = 1
const STORE_NAME = 'recordings'

function openDb() {
  return new Promise((resolve, reject) => {
    if (!('indexedDB' in globalThis)) {
      reject(new Error('IndexedDB is not available in this browser.'))
      return
    }

    const request = indexedDB.open(DB_NAME, DB_VERSION)
    request.onupgradeneeded = () => {
      const db = request.result
      if (!db.objectStoreNames.contains(STORE_NAME)) {
        db.createObjectStore(STORE_NAME, { keyPath: 'sessionId' })
      }
    }
    request.onsuccess = () => resolve(request.result)
    request.onerror = () => reject(request.error || new Error('Could not open local audio storage.'))
  })
}

export async function saveSessionAudio(sessionId, blob, metadata = {}) {
  if (!blob || !sessionId) return false
  const db = await openDb()

  return new Promise((resolve, reject) => {
    const tx = db.transaction(STORE_NAME, 'readwrite')
    tx.objectStore(STORE_NAME).put({
      sessionId,
      blob,
      metadata,
      savedAt: new Date().toISOString(),
    })
    tx.oncomplete = () => {
      db.close()
      resolve(true)
    }
    tx.onerror = () => {
      const error = tx.error || new Error('Could not save the recording locally.')
      db.close()
      reject(error)
    }
  })
}

export async function getSessionAudio(sessionId) {
  const db = await openDb()
  return new Promise((resolve, reject) => {
    const tx = db.transaction(STORE_NAME, 'readonly')
    const request = tx.objectStore(STORE_NAME).get(sessionId)
    request.onsuccess = () => {
      db.close()
      resolve(request.result || null)
    }
    request.onerror = () => {
      const error = request.error || new Error('Could not read the recording.')
      db.close()
      reject(error)
    }
  })
}

export async function deleteSessionAudio(sessionId) {
  if (!sessionId || !('indexedDB' in globalThis)) return false
  const db = await openDb()
  return new Promise((resolve, reject) => {
    const tx = db.transaction(STORE_NAME, 'readwrite')
    tx.objectStore(STORE_NAME).delete(sessionId)
    tx.oncomplete = () => {
      db.close()
      resolve(true)
    }
    tx.onerror = () => {
      const error = tx.error || new Error('Could not delete the recording.')
      db.close()
      reject(error)
    }
  })
}
