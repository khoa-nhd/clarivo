# Full analysis integration changes

This version upgrades the previous integrated build so Audio and Vision are actual independent analyses rather than media that are merely captured for later use.

## Backend

New endpoints:

- `POST /api/analyze/audio`
- `POST /api/analyze/vision`

The older `POST /api/analyze/delivery` endpoint is kept for compatibility.

Audio v11 uses the reviewed web transcript for text-derived metrics and analyzes the recorded WAV for pace/pause/audibility signals.

Vision v11 analyzes the saved camera recording with OpenVINO face/head/gaze models plus the pose model.

## Frontend queue

When a queued session starts, Clarivo launches three independent tasks:

- Content
- Voice
- Visual

The report is assembled from whichever delivery analyses finish successfully, so a Visual failure no longer prevents Voice scoring.

## UI

The report intentionally remains compact. It exposes:

Voice:
- score
- WPM
- pause quality
- audibility
- fillers only when reliable

Visual:
- score
- attention
- posture
- gesture level

The detailed raw v11 metrics remain inside the analyzer and are not dumped into the user interface.
