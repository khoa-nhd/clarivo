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

/** Matches the backend's own ceiling: 5,000 frames is 41 minutes at 2 fps. */
const MAX_FRAMES = 5000

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
// lifetime of the landmarker, not of one call, and the landmarkers are shared
// singletons because reloading them costs tens of megabytes.
//
// This counter is therefore advanced once per sampled frame and never derived
// from the position in the video and never rewound. An earlier version computed
// the timestamp from a cursor read at the start of the run plus the frame's
// offset, which looked monotonic but was not: two runs that overlapped both
// read the same starting cursor, so the second run's first frame arrived at the
// landmarker as timestamp 0 after the first run had already reached millions,
// and MediaPipe rejected the whole graph.
const TIMESTAMP_STEP_MS = 50
let timestampCursor = 0

function nextTimestamp() {
  timestampCursor += TIMESTAMP_STEP_MS
  return timestampCursor
}

// Overlapping runs are the other half of that bug, and no timestamp scheme
// fixes them: `detectForVideo` is stateful per landmarker, so two interleaved
// runs corrupt each other's graph regardless. They are serialised instead. In
// the app this happens when a manual "re-run voice & visual" lands while the
// queue is already analysing another session.
let pending = Promise.resolve()

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
          // The defaults are 0.5 and far too strict for a presenter who turns
          // to a slide: measured against OpenVINO on the same clip, the face was
          // found in 1 frame of 24 where OpenVINO found it in 23 of 23. A missed
          // face is not a neutral outcome - it removes the frame from the
          // attention evidence entirely.
          minFaceDetectionConfidence: 0.2,
          minFacePresenceConfidence: 0.2,
          minTrackingConfidence: 0.2,
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
 * The matrix is column-major, so the element at row i and column j is m[j*4+i].
 * Only the rotation block matters, decomposed about the axes head pose is
 * actually described in: yaw about the vertical axis (turning to a slide),
 * pitch about the horizontal axis (nodding), roll about the viewing axis
 * (tilting).
 *
 * The previous version used the ZYX convention, which labels a different axis
 * "yaw". Verified against rotations with known angles, it reported a 30 degree
 * head turn as 30 degrees of *pitch*, a 20 degree nod as 20 degrees of *roll*,
 * and a 15 degree tilt as -15 degrees of *yaw* - every axis shifted by one. The
 * scorer treats the three very differently, so every head turn in every
 * browser-analysed recording was graded against the thresholds for nodding.
 *
 * It had a passing test, which tested nothing: the test built its input
 * matrices with the same mistaken convention the decomposition used, so the two
 * errors cancelled. The test below is built from real axis rotations instead.
 *
 * The absolute zero does not have to match OpenVINO's - the scorer calibrates a
 * per-session baseline and works in angles relative to it - but the axes and
 * the scale do.
 */
function headPoseFromMatrix(matrix) {
  if (!matrix || matrix.length < 16) return null
  const at = (row, col) => matrix[col * 4 + row]

  const r02 = at(0, 2), r12 = at(1, 2), r22 = at(2, 2)
  const r10 = at(1, 0), r11 = at(1, 1)

  const cosPitch = Math.hypot(r02, r22)
  if (!Number.isFinite(cosPitch) || cosPitch < 1e-6) return null

  const yaw = Math.atan2(r02, r22) * DEG
  const pitch = Math.atan2(-r12, cosPitch) * DEG
  // Roll is negated to match the handedness the scorer was built against. On
  // the one frame where both models saw the same face, OpenVINO read +15.5 and
  // this matrix -18.4; the eye-line angle from the pose landmarks, which is
  // unambiguous geometry, agreed with OpenVINO's sign. Two independent sources
  // against one. It matters because roll is what the posture stage uses to
  // cancel camera tilt, and backwards it would add the tilt instead.
  const roll = -Math.atan2(r10, r11) * DEG
  if (![yaw, pitch, roll].every(Number.isFinite)) return null
  return [yaw, pitch, roll]
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
export function buildVisionTimeline(videoBlob, options = {}) {
  const run = pending.then(
    () => runTimeline(videoBlob, options),
    () => runTimeline(videoBlob, options),
  )
  // Keep the chain alive after a failure, but do not let it reject unhandled.
  pending = run.then(() => {}, () => {})
  return run
}

/** Whether a failure is MediaPipe refusing a timestamp it has already passed. */
function isTimestampFault(error) {
  return /timestamp mismatch|not strictly monotonic/i.test(String(error?.message || error))
}

async function runTimeline(videoBlob, options) {
  try {
    return await sampleTimeline(videoBlob, options)
  } catch (error) {
    if (!isTimestampFault(error)) throw error
    // The landmarker's graph is now in a state this code cannot talk its way
    // out of. Drop it and build a fresh one rather than leaving visual analysis
    // broken until the page is reloaded.
    loaderPromise = null
    return sampleTimeline(videoBlob, options)
  }
}

async function sampleTimeline(videoBlob, { durationSeconds = 0, onProgress, signal } = {}) {
  if (!browserVisionSupported()) throw new Error('This browser cannot run visual analysis.')
  const { face, pose } = await loadModels()
  const { video, url } = await loadVideo(videoBlob)

  try {
    // The recorder timed the take with a wall clock. A MediaRecorder WebM often
    // carries no duration header at all, and what the element reports for one
    // ranges from correct to Infinity depending on the browser - so the
    // measured value wins where there is one.
    const reported = Number(durationSeconds) || 0
    const container = Number.isFinite(video.duration) && video.duration > 0 ? video.duration : 0
    const duration = reported > 0 ? reported : container
    if (!(duration > 0)) throw new Error('This recording has no readable duration.')

    const width = video.videoWidth || 640
    const height = video.videoHeight || 480
    const step = 1 / SAMPLE_FPS
    // Bounded on purpose. A wrong duration must cost a short analysis, not tens
    // of thousands of inference calls - and the backend refuses more than 5,000
    // frames anyway.
    const total = Math.min(MAX_FRAMES, Math.max(1, Math.floor(duration * SAMPLE_FPS)))
    const frames = []

    for (let i = 0; i < total; i += 1) {
      if (signal?.aborted) throw new Error('Visual analysis was cancelled.')
      const at = Math.min(i * step, Math.max(0, duration - 0.001))
      await seekTo(video, at)
      const stamp = nextTimestamp()

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
    URL.revokeObjectURL(url)
    video.removeAttribute('src')
    video.load()
  }
}
