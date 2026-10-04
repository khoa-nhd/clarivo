// Run the vision models in the browser and produce the timeline the backend scores.
//
// Visual analysis used to need a machine carrying OpenVINO, OpenCV, Ultralytics
// and torch - measured at about 970 MB of wheels plus 58 MB of weights. A
// serverless function allows 500 MB, and a camera recording cannot reach one
// anyway through a 4.5 MB request body cap. So the deployed site could never
// score video, whatever it was configured with.
//
// The models run here instead, on the viewer's own device, and only what they
// saw is sent: per sampled frame a face count, a head pose, a gaze estimate and
// a set of pose keypoints. That is a few hundred kilobytes, and the backend
// scores it with exactly the same decision layer the local OpenVINO path uses -
// the thresholds, the calibration and the temporal rules are shared, not
// reimplemented. The video itself never leaves the browser.

// The WASM runtime and the model weights are tens of megabytes, so they are
// fetched at first use rather than bundled. A blocked CDN is reported as
// "visual analysis unavailable" rather than failing the whole session.
const WASM_ROOT = 'https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@0.10.14/wasm'
const FACE_MODEL = 'https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task'
const POSE_MODEL = 'https://storage.googleapis.com/mediapipe-models/pose_landmarker/pose_landmarker_lite/float16/1/pose_landmarker_lite.task'

/** Sampling rate. Matches the backend default so the temporal rules line up. */
export const SAMPLE_FPS = 2

// COCO order, which is what the scorer indexes. MediaPipe's pose model uses its
// own 33-point layout, so the eight joints the posture and gesture rules read
// have to be mapped across rather than passed through.
const MEDIAPIPE_TO_COCO = [
  ['nose', 0], ['left_eye', 2], ['right_eye', 5], ['left_ear', 7], ['right_ear', 8],
  ['left_shoulder', 11], ['right_shoulder', 12], ['left_elbow', 13], ['right_elbow', 14],
  ['left_wrist', 15], ['right_wrist', 16], ['left_hip', 23], ['right_hip', 24],
]
const COCO_INDEX = {
  nose: 0, left_eye: 1, right_eye: 2, left_ear: 3, right_ear: 4,
  left_shoulder: 5, right_shoulder: 6, left_elbow: 7, right_elbow: 8,
  left_wrist: 9, right_wrist: 10, left_hip: 11, right_hip: 12,
}

let loaderPromise = null

// MediaPipe's VIDEO mode requires timestamps that increase strictly over the
// lifetime of the landmarker, not of one call. The landmarkers are reused
// between analyses - reloading them costs tens of megabytes - so a second run
// that restarted its clock at zero was rejected outright with "Packet timestamp
// mismatch", meaning every session after the first failed. This cursor is never
// rewound.
let timestampCursor = 0

async function loadModels() {
  if (!loaderPromise) {
    loaderPromise = (async () => {
      // Imported here rather than at module scope so the ~140 kB wrapper is not
      // in the bundle every visitor downloads - most never record anything.
      const { FilesetResolver, FaceLandmarker, PoseLandmarker } = await import('@mediapipe/tasks-vision')
      const fileset = await FilesetResolver.forVisionTasks(WASM_ROOT)
      const [face, pose] = await Promise.all([
        FaceLandmarker.createFromOptions(fileset, {
          baseOptions: { modelAssetPath: FACE_MODEL, delegate: 'GPU' },
          runningMode: 'VIDEO',
          numFaces: 1,
          // The transformation matrix is the head pose; the blendshapes carry
          // where the eyes are pointing inside that head.
          outputFacialTransformationMatrixes: true,
          outputFaceBlendshapes: true,
        }),
        PoseLandmarker.createFromOptions(fileset, {
          baseOptions: { modelAssetPath: POSE_MODEL, delegate: 'GPU' },
          runningMode: 'VIDEO',
          numPoses: 1,
        }),
      ])
      return { face, pose }
    })().catch((error) => {
      loaderPromise = null  // let a later attempt retry rather than cache the failure
      throw error
    })
  }
  return loaderPromise
}

/** Whether this browser can run the models at all. */
export function browserVisionSupported() {
  return typeof WebAssembly === 'object' && typeof document !== 'undefined'
}

const DEG = 180 / Math.PI

/** Head pose in degrees from MediaPipe's 4x4 facial transformation matrix.
 *
 * The matrix is column-major. Only the rotation block matters here, decomposed
 * as yaw-pitch-roll. The absolute zero does not have to match OpenVINO's: the
 * scorer calibrates a per-session baseline and works in angles relative to it,
 * so a constant offset cancels. The *scale* does matter, which is why this
 * returns degrees rather than the raw matrix.
 */
function headPoseFromMatrix(matrix) {
  if (!matrix || matrix.length < 16) return null
  const m = matrix
  // Column-major: m[col * 4 + row].
  const r00 = m[0], r10 = m[1], r20 = m[2]
  const r21 = m[6], r22 = m[10]
  const sy = Math.hypot(r00, r10)
  if (!Number.isFinite(sy) || sy < 1e-6) return null
  const pitch = Math.atan2(-r20, sy) * DEG
  const yaw = Math.atan2(r10, r00) * DEG
  const roll = Math.atan2(r21, r22) * DEG
  if (![pitch, yaw, roll].every(Number.isFinite)) return null
  // MediaPipe's yaw grows to the subject's right where OpenVINO's grows to the
  // left. Every rule downstream is symmetric around the calibrated baseline, so
  // this only keeps the two sources describing the same turn the same way.
  return [-yaw, pitch, roll]
}

function blendshape(categories, name) {
  const found = categories?.find((c) => c.categoryName === name)
  return found ? found.score : 0
}

/** Eye direction in degrees, from the eye blendshapes.
 *
 * This is an estimate, not a measurement: the blendshapes are activation
 * strengths in 0..1, mapped here onto the angular range a human eye actually
 * covers. It is reported with a low reliability so the scorer blends it mostly
 * with head pose, which is measured. Where no face is found there is no gaze.
 */
function gazeFromBlendshapes(categories) {
  if (!categories?.length) return null
  const lookOut = blendshape(categories, 'eyeLookOutLeft') + blendshape(categories, 'eyeLookOutRight')
  const lookIn = blendshape(categories, 'eyeLookInLeft') + blendshape(categories, 'eyeLookInRight')
  const lookUp = blendshape(categories, 'eyeLookUpLeft') + blendshape(categories, 'eyeLookUpRight')
  const lookDown = blendshape(categories, 'eyeLookDownLeft') + blendshape(categories, 'eyeLookDownRight')
  // Roughly +-25 degrees of comfortable eye rotation, halved because each pair
  // of blendshapes sums two eyes.
  const yaw = ((lookOut - lookIn) / 2) * 25
  const pitch = ((lookUp - lookDown) / 2) * 20
  if (!Number.isFinite(yaw) || !Number.isFinite(pitch)) return null
  // Deliberately modest. The backend blends gaze with head pose in proportion
  // to this value, and claiming the confidence of a dedicated gaze model for a
  // blendshape estimate would be dishonest.
  return [yaw, pitch, 0.35]
}

/** MediaPipe landmarks to the COCO-indexed pixel keypoints the scorer reads. */
function poseFromLandmarks(landmarks, width, height) {
  if (!landmarks?.length) return null
  const xy = Array.from({ length: 13 }, () => [0, 0])
  const conf = new Array(13).fill(0)
  let seen = 0
  for (const [name, sourceIndex] of MEDIAPIPE_TO_COCO) {
    const point = landmarks[sourceIndex]
    if (!point) continue
    const target = COCO_INDEX[name]
    // Normalised coordinates would distort every angle the posture rules
    // measure unless the frame happens to be square. Scale to pixels.
    xy[target] = [point.x * width, point.y * height]
    const visibility = typeof point.visibility === 'number' ? point.visibility : 1
    conf[target] = Math.max(0, Math.min(1, visibility))
    if (conf[target] > 0) seen += 1
  }
  return seen ? { xy, conf } : null
}

function seekTo(video, seconds) {
  return new Promise((resolve, reject) => {
    const onSeeked = () => { cleanup(); resolve() }
    const onError = () => { cleanup(); reject(new Error('Could not read this recording.')) }
    const cleanup = () => {
      video.removeEventListener('seeked', onSeeked)
      video.removeEventListener('error', onError)
    }
    video.addEventListener('seeked', onSeeked)
    video.addEventListener('error', onError)
    video.currentTime = seconds
  })
}

function loadVideo(blob) {
  return new Promise((resolve, reject) => {
    const url = URL.createObjectURL(blob)
    const video = document.createElement('video')
    video.preload = 'auto'
    video.muted = true
    video.playsInline = true
    video.onloadeddata = () => resolve({ video, url })
    video.onerror = () => { URL.revokeObjectURL(url); reject(new Error('Could not decode this recording.')) }
    video.src = url
  })
}

/** Run the models over a recording and return the timeline the backend scores.
 *
 * @param {Blob} videoBlob the recording, which never leaves the browser
 * @param {{durationSeconds?: number, onProgress?: Function, signal?: AbortSignal}} options
 */
export async function buildVisionTimeline(videoBlob, { durationSeconds = 0, onProgress, signal } = {}) {
  if (!browserVisionSupported()) throw new Error('This browser cannot run visual analysis.')
  const { face, pose } = await loadModels()
  const { video, url } = await loadVideo(videoBlob)
  let lastStamp = timestampCursor

  try {
    const duration = Number.isFinite(video.duration) && video.duration > 0
      ? video.duration
      : Number(durationSeconds) || 0
    if (!(duration > 0)) throw new Error('This recording has no readable duration.')

    const width = video.videoWidth || 640
    const height = video.videoHeight || 480
    const step = 1 / SAMPLE_FPS
    const total = Math.max(1, Math.floor(duration * SAMPLE_FPS))
    const frames = []

    for (let i = 0; i < total; i += 1) {
      if (signal?.aborted) throw new Error('Visual analysis was cancelled.')
      const at = Math.min(i * step, Math.max(0, duration - 0.001))
      await seekTo(video, at)
      const stamp = timestampCursor + Math.round(at * 1000) + i
      lastStamp = Math.max(lastStamp, stamp)

      const record = { face_count: 0, head_pose: null, gaze: null, pose: null, pose_attempted: true }

      const faceResult = face.detectForVideo(video, stamp)
      const matrix = faceResult?.facialTransformationMatrixes?.[0]?.data
      const headPose = headPoseFromMatrix(matrix)
      if (headPose) {
        record.face_count = 1
        record.head_pose = headPose
        record.gaze = gazeFromBlendshapes(faceResult?.faceBlendshapes?.[0]?.categories)
      }

      const poseResult = pose.detectForVideo(video, stamp)
      record.pose = poseFromLandmarks(poseResult?.landmarks?.[0], width, height)

      frames.push(record)
      onProgress?.({ done: i + 1, total })
    }

    return { frames, durationSeconds: duration, sampleFps: SAMPLE_FPS }
  } finally {
    // Advance past whatever this run used, including on an error or a cancel,
    // so the next analysis cannot hand the landmarker an older timestamp.
    timestampCursor = lastStamp + 1000
    URL.revokeObjectURL(url)
    video.removeAttribute('src')
    video.load()
  }
}
