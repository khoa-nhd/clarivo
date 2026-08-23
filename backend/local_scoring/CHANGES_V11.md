# Clarivo v11 — adaptive attention, upper-body posture, audio reliability

## Camera attention

v11 solves the framing conflict between eye gaze and posture:

- **Close / large face:** use OpenVINO eye-gaze estimation together with head pose.
- **Far / small face:** automatically ignore eye gaze and use head direction only.
- Gaze is enabled only when both the face-size threshold and eye-crop reliability pass.
- Head and gaze have separate calibration references, so switching modes does not mix incompatible angles.
- Short detector misses and brief glances are still smoothed temporally.

The final report records how many frames used `gaze` vs `head-only`.

## Posture

Hips are no longer required. Two modes are available:

- `upper_body`: face/head + both shoulders.
- `full_torso`: shoulders + hips, when available.

Posture includes:

- shoulder level / sideways lean,
- head centering,
- head pitch / carriage,
- shoulder-to-torso alignment when hips are visible,
- shoulder/hip twist/asymmetry when hips are visible,
- **forward/backward lean proxy** using projection compression.

Forward/backward lean cannot be recovered perfectly from a single 2-D webcam. v11 therefore uses a conservative projection-compression proxy and gives it limited weight rather than pretending it is exact 3-D pose.

## Gesture

Gesture remains body-relative (elbows/wrists in a shoulder-attached coordinate system), so moving or leaning the whole torso should not be counted as a hand gesture. Gesture is informational and is not part of the vision overall score.

## Audio

- Pace scoring uses a broader presentation-friendly curve.
- Local-ASR pace scores are reliability-adjusted instead of treated as exact.
- Filler rate is additionally reported per 100 words.
- If local filler evidence is too weak, `scores.filler` can be `null` rather than a misleading number.
- External/web transcripts receive full filler reliability.
- Pause scoring focuses on actual long/excessive silence and no longer requires the presenter to pause frequently.
- Audibility is primarily SNR + clipping; absolute microphone dBFS is only a weak guard.
- Live voice meter is calibrated around ~40/100 for normal speech; it is not the same as the final audibility score.

## Realtime pace

The preview waits for at least two broadly consistent long-window ASR estimates before showing WPM. A contradictory decode is rejected and the UI shows `RECHECKING` instead of jumping to a wrong number.
