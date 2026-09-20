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

Local OpenVINO voice/visual analysis is a separate, much larger install
(OpenVINO + Ultralytics + model weights). Set it up once with
`backend\setup_local_scoring.bat`, then set `LOCAL_SCORING_ENABLED=true` in
`backend\.env`.

To publish with Voice + Visual working online for free, see
`DEPLOY_TUNNEL.md` (Vercel for content, a Cloudflare Tunnel to this machine for
the OpenVINO analysis).

Other docs:
- `RUN_LEARNING_LOOP_WINDOWS.md` — exact Windows commands
- `LEARNING_LOOP_IMPLEMENTATION.md` — feature and architecture map
- `backend/BENCHMARKS.md` — how to reproduce every accuracy/performance number
- `DEPLOY_TUNNEL.md` — free public deploy with full features
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
