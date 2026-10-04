# Clarivo — Learning Loop + Content + Delivery

Clarivo now supports the complete practice loop:

**Topic Library → Main Presentation → Editable Whisper Transcript → Content / Voice / Visual Analysis → A/B/C Interactive Drills → 5-Criterion Q&A Evaluation → Coverage / Dynamic Stopping → Final Learning Summary.**

The existing seven-criterion Main Evaluator remains unchanged. The new drill system is a separate layer above it.

## Quick start (Windows)

Double-click **`start.bat`** in the project root. It sets everything up on the
first run and launches the app on every run:

1. creates `backend\.venv` if missing
2. installs the backend packages if missing
3. creates `backend\.env` from `.env.example` if missing
4. runs `npm install` if `frontend/node_modules` is missing
5. starts the backend (port 8000) and frontend (port 5173) in two windows
6. waits for both, then opens <http://localhost:5173>

The first run takes a few minutes; later runs take a few seconds. To stop the
project, close the two server windows.

It starts in **mock AI mode**, so it works with no API key and costs no quota.
To use the real AI, open `backend\.env` and set:

```
AI_PROVIDER=cloudflare
TRANSCRIPTION_PROVIDER=cloudflare
CLOUDFLARE_ACCOUNT_ID=your-account-id
CLOUDFLARE_AUTH_TOKEN=your-workers-ai-token
```

then run `start.bat` again.

Local OpenVINO voice/visual analysis is a separate, larger install. Set it up
once with `backend\setup_local_scoring.bat`, then set `LOCAL_SCORING_ENABLED=true`
in `backend\.env`.

The pose model runs through its exported OpenVINO IR, so ultralytics and torch
are needed only to produce that IR and the setup script removes them again
afterwards. Measured in this project's venv that is 517 MB of the install:

| | before | after |
|---|---|---|
| vision runtime | 923 MB | 408 MB |
| of which torch | 509 MB | — |

Verified by running the full pipeline in a clean environment with torch and
ultralytics absent: the same clip scores 80.2 either way.

Deployed on Vercel the site runs every feature, including visual analysis.

Visual analysis has two paths and the backend reports which one it can serve:

- **Locally** the OpenVINO stack runs on this machine over the uploaded video.
- **Deployed** the models run in the viewer's browser (MediaPipe) and only the
  per-frame signals are posted to `/api/analyze/vision-timeline`, where the same
  scoring code grades them. The recording never leaves the browser.

The second path exists because the first cannot be deployed: the stack measures
about 970 MB of wheels against Vercel's 500 MB limit, and a camera recording is
far over the 4.5 MB request body limit regardless. A minute of timeline is about
47 kB.

A recording is capped at the length whose 16 kHz WAV fits the 4.5 MB serverless
request limit - about 2m24s deployed, the full 5 minutes locally.

Other docs:
- `RUN_LEARNING_LOOP_WINDOWS.md` — exact Windows commands
- `LEARNING_LOOP_IMPLEMENTATION.md` — feature and architecture map
- `backend/BENCHMARKS.md` — how to reproduce every accuracy/performance number
- `DEPLOY_PUBLIC_VERCEL.md` — serverless-only deploy and its platform limits

## Frontend starter library
Edit `frontend/src/data/topicLibrary.js` to add or change prepared topics.

## Backend drill endpoints
- `POST /api/drills/generate`
- `POST /api/drills/evaluate`
- `POST /api/drills/finalize`

## Q&A criteria
- Accuracy
- Directness
- Consistency
- Relevance
- Audience Fit

Default `DRILL_MAX_ROUNDS=3`.

## Q&A / Topic Library v2 update

See `QNA_TOPIC_V2_CHANGES.md` for the isolated Q&A scorer, Overall after Q&A, same-type challenge replacement, audience-style questions, main-quality Q&A guard, and refreshable Topic Library.

# Final public package
