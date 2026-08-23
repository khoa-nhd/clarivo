# Clarivo Phase 20 Audio/Vision Integration

This project is based on `clarivo-learning-loop-v2` and replaces only the local Audio/Vision scoring core with the uploaded Phase 20 cross-metric-hardened analyzers.

## Transcript policy

Clarivo continues to use the existing Cloudflare Whisper transcription flow and the user's editable transcript. The Phase 20 local/OpenVINO Whisper path is intentionally not used for web sessions.

The audio scorer receives the existing Cloudflare transcript for transcript-derived delivery metrics. Phase 20's domain rewrite path is disabled for externally supplied Clarivo transcripts so it cannot silently replace the user's reviewed text.

## New Audio signals used

- Speech/no-speech evidence gate
- WPM and articulation WPM
- Pause control
- Audibility / SNR
- Volume stability
- Pace stability
- Fluency
- Voice activity ratio
- Dead-silence warning
- Cross-metric slow-pace guards
- Transcript filler count
- Acoustic prolonged-vowel hesitation detection
- Combined filler count
- Filler hallucination/plausibility guard

### Filler source

The UI now reports Phase 20 combined fillers:

`combined filler = transcript non-lexical fillers + conservative prolonged-vowel acoustic hesitations`

Cloudflare/user transcript remains the text source. The new analyzer contributes the acoustic hesitation evidence.

## New Vision signals used

- Camera attention
- Presence
- Head stability
- Posture
- Direct/forward attention percentages
- Look-away episode count and sustained duration
- 2.5 s gaze temporal buffer + repeated-episode accumulation
- 3.5 s head-turn temporal buffer + repeated-episode accumulation
- 4.0 s posture violation threshold + repeated deviation accumulation
- Short orientation hold / soft decay
- Pose-backed presence
- Gesture activity level/events (informational, not a forced numeric grade)

## UI policy

The backend retains more detailed raw metrics, but the main Delivery report only surfaces metrics that are understandable and actionable. Advanced geometry such as raw yaw/pitch, shoulder angles, keypoint confidences, and internal posture components remains hidden from the default report.

## Tests

`backend/tests/test_phase20_integration.py` checks:

- Phase 20 cross-metric pace behavior
- Safe acoustic filler helper behavior
- New compact audio payload
- New temporal vision flags in the compact payload

The existing structured-output and Q&A learning-loop tests remain intact.
