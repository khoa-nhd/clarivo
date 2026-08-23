# Posture v9

The previous posture scorer calibrated every posture feature to the first few frames. That could make an initially slouched or tilted pose look "perfect" because the bad pose became the baseline.

v9 changes the posture grade to camera-rotation-resistant structural geometry:

- shoulder-to-torso orthogonality (largest weight)
- head centering relative to the shoulder/torso coordinate system
- shoulder-to-hip parallelism when both hips are visible
- head roll relative to the shoulder line (small supporting weight)

The startup warm-up now estimates only whole-body lean/camera context for diagnostics. It cannot normalize away a structurally bad posture.

A one-hip frame may be used as a lower-confidence diagnostic frame, but reliable final posture requires enough good frames and pose quality. Gesture and camera attention are separate from posture.

## Important reliability change

- Head-pose roll is **not** used in the posture grade. It remains a diagnostic only.
- Structural posture can be scored before warm-up finishes; warm-up no longer gates the result.
- Final posture availability depends on enough reliable skeleton frames, not on whether a baseline was successfully learned.
