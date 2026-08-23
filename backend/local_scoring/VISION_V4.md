# Clarivo Vision v4

## Why v3 could show `Posture: FRAME BODY` even when you could see shoulders and hips

The camera image being visually clear does not mean the pose model assigned a high confidence to every keypoint. v3 required every shoulder and hip to clear a relatively high confidence gate and also required a strict calibration/reliability fraction. A single low-confidence hip could therefore disable posture.

v4 uses lower keypoint gates plus an explicit reliability score. It calibrates after four reliable torso frames and can use one hip at reduced confidence if the other hip is temporarily occluded.

## Gesture changes

v3 only compared wrist movement in raw pixels. That failed when wrists were cropped, slightly low-confidence, or when camera/body translation changed the apparent motion.

v4 uses wrists **and elbows**, transforms them into shoulder-centered coordinates, and divides motion by shoulder width. This produces a scale-independent gesture activity signal.

Gesture remains informational and is not used in the overall vision score.

## Preview diagnostics

The preview draws the pose skeleton for shoulders, hips, elbows and wrists. The right panel shows:

- `Pose`: whether pose keypoints are being accepted, plus pose quality.
- `Posture`: calibration/good/adjust/unavailable.
- `Gesture`: tracking/low/moderate/high, active percentage and event count.

## Final JSON diagnostics

Look at:

- `pose_valid_frames`
- `pose_attempts`
- `pose_reliability`
- `mean_pose_keypoint_quality`
- `posture_score_available`
- `keypoint_visibility_percent`
- `arm_keypoint_visible_percent`
- `gesture_reliable`
- `gesture_level`
- `gesture_activity_percent`
- `gesture_event_count`
