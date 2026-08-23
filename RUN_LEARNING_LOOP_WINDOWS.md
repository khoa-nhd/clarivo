# Clarivo Learning Loop — Windows run guide

This build adds Topic Library + A/B/C Interactive Drills + 5-criterion Q&A evaluation + Coverage + Dynamic Stopping + Final Learning Summary on top of the existing Content / Voice / Visual pipeline.

## 1. Backend

Open PowerShell in the project root:

```powershell
cd backend
```

First run only:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-local.txt
.\.venv\Scripts\python.exe -m local_scoring.setup_delivery_models
```

Create the environment file if it does not exist:

```powershell
Copy-Item .env.example .env
notepad .env
```

Recommended local configuration:

```env
AI_PROVIDER=cloudflare
TRANSCRIPTION_PROVIDER=cloudflare

CLOUDFLARE_ACCOUNT_ID=YOUR_REAL_ACCOUNT_ID
CLOUDFLARE_AUTH_TOKEN=YOUR_REAL_TOKEN
CLOUDFLARE_MODEL=@cf/qwen/qwen3-30b-a3b-fp8
CLOUDFLARE_TRANSCRIPTION_MODEL=@cf/openai/whisper-large-v3-turbo

AI_TIMEOUT_SECONDS=120
AI_MAX_TOKENS=3000
AI_TEMPERATURE=0.1
AI_MAX_ATTEMPTS=2
TRANSCRIPTION_TIMEOUT_SECONDS=120

MAX_AUDIO_BYTES=3500000
MAX_RECORDING_SECONDS=300
MAX_TRANSCRIPT_CHARS=20000
MAX_REFERENCE_CHARS=20000
ALLOWED_ORIGINS=

LOCAL_SCORING_ENABLED=true
LOCAL_MODELS_DIR=
LOCAL_CACHE_DIR=
LOCAL_VISION_DEVICE=RECOMMENDED
LOCAL_POSE_DEVICE=RECOMMENDED
LOCAL_SAMPLE_FPS=2.0
LOCAL_MAX_AUDIO_WAV_BYTES=16000000
LOCAL_MAX_VIDEO_BYTES=80000000

DRILL_MAX_ROUNDS=3
```

Run backend:

```powershell
.\.venv\Scripts\python.exe -m uvicorn main:app --reload --port 8000
```

Check:

```text
http://127.0.0.1:8000/api/health
```

You should see `learning_loop.enabled: true`. For full local delivery analysis, `delivery_analysis.enabled`, `audio_ready`, and `vision_ready` should also be true.

## 2. Frontend

Open a second PowerShell terminal:

```powershell
cd frontend
npm.cmd install
npm.cmd run dev
```

Open:

```text
http://localhost:5173
```

## 3. End-to-end test

1. Pick `Explain Merge Sort` from Topic Library.
2. Confirm the task brief, study keywords, and recommended audience.
3. Change Audience if desired — the recommendation is not mandatory.
4. Record a 20–30 second explanation or paste a transcript.
5. Review/edit the transcript.
6. Submit to the queue.
7. Wait for Content / Voice / Visual analysis and the three A/B/C challenges.
8. Select one challenge.
9. Record a 30–60 second Q&A answer or type it manually.
10. Review/edit the Q&A transcript.
11. Submit the answer.
12. Inspect the five Q&A scores: Accuracy, Directness, Consistency, Relevance, Audience Fit.
13. Continue until Clarivo stops automatically, reaches 3 rounds, or press `Finish practice`.
14. Review Final Learning Summary and Coverage.

## 4. Test without Cloudflare

Set:

```env
AI_PROVIDER=mock
TRANSCRIPTION_PROVIDER=mock
```

The drill endpoints also have mock responses, so the complete state/UI flow can be tested without consuming API quota. Real quality requires Cloudflare mode.

## 5. Updating the existing Vercel deployment

No new secret is required. Optional backend environment variable:

```text
DRILL_MAX_ROUNDS=3
```

Push the updated repo:

```powershell
git add .
git commit -m "Add Clarivo interactive learning loop"
git push
```

Vercel will redeploy the existing frontend/backend projects from the same repository. The public Cloudflare Content + Q&A loop works on Vercel. Keep `LOCAL_SCORING_ENABLED=false` on Vercel unless the Audio/Vision OpenVINO runtime is hosted separately.
