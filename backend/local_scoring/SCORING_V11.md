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

Reliability-weighted components. These are the values in `AudioConfig`; the
figures previously printed here (28/25/24/8/8/7) did not match the code.

- audibility (`weight_volume`): 30%
- pause control (`weight_pause`): 27%
- pace (`weight_pace`): 18% × transcript reliability
- filler (`weight_filler`): 10% × filler reliability
- volume stability (`weight_volume_stability`): 8%
- pace stability (`weight_pace_stability`): 7%

Weights are normalised over whichever components are available, so a component
that cannot be measured does not silently drag the total down.

### Filler

Both rates are reported: `fillers_per_minute` (used for scoring) and
`fillers_per_100_words` (rate independent of speaking speed). Local Whisper can
suppress disfluencies, so local filler reliability is conservative. A
web/external transcript is trusted at full reliability.

## Speech detection

The speech/silence threshold is chosen by Otsu's method over the frame-energy
histogram in dB, with the resulting class separation deciding whether the
recording is bimodal (speech plus background) at all. The earlier
percentile-based estimate assumed the quietest 18% of frames were always
background, which fails once speech fills most of the recording. See
`vad_benchmark.py` for the measured before/after.
