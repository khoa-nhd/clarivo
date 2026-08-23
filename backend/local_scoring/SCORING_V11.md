# Clarivo v11 scoring notes

## Attention

Attention uses adaptive sensor selection.

### Close face

`attention ~= eye gaze + head pose`

Eye gaze has the larger share, but head pose stabilizes noisy eye estimates.

### Far face

`attention = head direction`

A small face is not penalized merely because eye gaze cannot be measured reliably.

Presence is based mostly on sustained out-of-frame time rather than isolated detector misses. Engagement is a robust combination of median, mean, lower-quartile orientation score and sustained looking-away time.

## Vision overall

When posture is reliable:

- Camera attention: 60%
- Head stability: 15%
- Posture: 25%

Each component is multiplied by measurement reliability. Gesture is not included.

## Posture

Upper-body mode uses:

- shoulder level,
- head centering,
- head pitch/carriage,
- head/shoulder projection compression.

Full-torso mode additionally uses:

- torso projection,
- shoulder/torso orthogonality,
- shoulder/hip alignment,
- left/right torso asymmetry.

Projection compression is a proxy for forward/backward bending. It is referenced to the least-compressed reliable geometry observed in the session. It is intentionally bounded because monocular 2-D video cannot perfectly recover depth.

## Audio overall

Reliability-weighted components:

- pause control: 28%
- audibility: 25%
- pace: 24% × transcript reliability
- volume stability: 8%
- filler: 8% × filler reliability (omitted if too unreliable)
- pace stability: 7%

### Filler

The raw filler rate is primarily evaluated as fillers per 100 words. Local Whisper can suppress disfluencies, so local filler reliability is conservative. A web/external transcript is trusted at full reliability.
