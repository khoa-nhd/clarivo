# Clarivo Phase 20 — Public deployment on the existing Vercel projects

This build removes the two development/status chips from the header and removes the small `+` button from Session queue. The main `+ New session` button remains.

## 1. Put this build into the existing GitHub repository

Use the existing repository connected to Vercel. Do not create a second Vercel project unless you intentionally want new URLs.

If your old local GitHub repository still exists, replace its project files with the files from this package while keeping the hidden `.git` folder.

Then open PowerShell in that Git repository and run:

```powershell
git status
git add .
git commit -m "Prepare Clarivo Phase 20 for public deployment"
git push origin main
```

Do not commit `backend/.env`. Secrets belong in Vercel Environment Variables.

## 2. Backend Vercel project

Existing backend project root directory:

```text
backend
```

Set these Production environment variables:

```env
AI_PROVIDER=cloudflare
TRANSCRIPTION_PROVIDER=cloudflare

CLOUDFLARE_ACCOUNT_ID=<your account id>
CLOUDFLARE_AUTH_TOKEN=<your token>

CLOUDFLARE_MODEL=@cf/qwen/qwen3-30b-a3b-fp8
CLOUDFLARE_TRANSCRIPTION_MODEL=@cf/openai/whisper-large-v3-turbo

AI_TIMEOUT_SECONDS=120
AI_MAX_TOKENS=3000
AI_TEMPERATURE=0.1
AI_MAX_ATTEMPTS=2
TRANSCRIPTION_TIMEOUT_SECONDS=120

AI_EVIDENCE_FIELDS=true
AI_CACHE_TTL_SECONDS=3600
AI_CACHE_MAX_ENTRIES=32
AI_RETRY_BACKOFF_SECONDS=1.0

MAX_AUDIO_BYTES=3500000
MAX_RECORDING_SECONDS=300
MAX_TRANSCRIPT_CHARS=20000
MAX_REFERENCE_CHARS=20000

DRILL_MAX_ROUNDS=3

ALLOWED_ORIGINS=https://clarivo-kohl.vercel.app

LOCAL_SCORING_ENABLED=false
```

### If the content report starts failing right after deploy

The report now includes per-dimension evidence and a transcript-vs-reference
comparison. Those add optional properties to the Workers AI function-call
schema, and that extended schema has **not** been exercised against the live
Qwen deployment - only against a local fake and the mock provider. If analysis
begins failing immediately after this deploy, set:

```env
AI_EVIDENCE_FIELDS=false
```

and redeploy the backend. That removes the extra fields from both the schema
and the prompt, returning the report to the previous seven-score behaviour. It
is a one-variable rollback; no code change is needed. Verify with a single
session, then decide whether to re-enable.

Important: keep `LOCAL_SCORING_ENABLED=false` on the current Vercel backend. The Phase 20 OpenVINO Audio/Vision stack is the local Intel analyzer and is not included in `backend/requirements.txt` used by the public serverless deployment.

After deployment, verify:

```text
https://clarivo-phi.vercel.app/api/health
```

Expected public values include:

```json
{
  "ok": true,
  "provider": "cloudflare",
  "transcription_provider": "cloudflare",
  "learning_loop": {
    "enabled": true,
    "qa_scoring_mode": "isolated_current_q_and_a",
    "same_type_followups": true,
    "topic_refresh": true
  }
}
```

For the current Vercel deployment, `delivery_analysis.enabled` is expected to be `false`.

## 3. Frontend Vercel project

Existing frontend project root directory:

```text
frontend
```

Set the Production environment variable:

```env
VITE_API_BASE_URL=https://clarivo-phi.vercel.app
```

There is no `/api` suffix and no trailing slash.

The frontend public URL is:

```text
https://clarivo-kohl.vercel.app
```

If both Vercel projects are connected to the same GitHub repository and branch, pushing to `main` normally creates deployments for both projects automatically. Otherwise use Vercel > Project > Deployments > Redeploy.

## 4. Test after deployment

1. Open `https://clarivo-phi.vercel.app/api/health`.
2. Confirm Cloudflare Qwen and Cloudflare Whisper are active.
3. Open `https://clarivo-kohl.vercel.app` in an incognito/private browser window.
4. Refresh Topic Library once.
5. Record a short explanation and confirm transcription works.
6. Submit the session and confirm Content scoring finishes.
7. Complete one Q&A drill and confirm the five Q&A scores and Overall after Q&A appear.
8. Refresh the page and confirm Session History remains in the browser.

## Enabling voice analysis on the public backend

`delivery_analysis.mode` reads `disabled` on the deployed backend because
`LOCAL_SCORING_ENABLED=false`. The two halves of that feature have very
different requirements, and only one of them can run on Vercel.

### Voice: possible, with one caveat

Measured against the real Vercel limits (docs, Aug 2026):

| Constraint | Vercel Hobby | Voice needs | Verdict |
|---|---|---|---|
| Bundle size (Python) | 500 MB | ~434 MB | fits |
| Max duration | 300 s | ~14 s for a 22 s clip | fits |
| Memory | 2 GB / 1 vCPU | well under | fits |
| Request body | **4.5 MB** | 32 KB/s of WAV | **caps length** |

Voice analysis needs no OpenVINO: on the web the transcript comes from
Cloudflare Whisper, so local ASR never runs and the analyzer is pure
NumPy/librosa DSP. Verified by running the production endpoint against a real
WAV with only `numpy`, `librosa` and `soundfile` installed - it returned a full
voice score with speaking time accurate to 0.03 s.

To enable it:

1. Append the three lines from `backend/requirements-vercel-voice.txt` to
   `backend/requirements.txt`.
2. Set `LOCAL_SCORING_ENABLED=true` on the backend project.
3. Set `MAX_RECORDING_SECONDS=140`. The browser uploads 16 kHz mono 16-bit WAV
   at 32 KB/s, so 4.5 MB is about 140 seconds. Without this, longer recordings
   are rejected by Vercel with a 413 before they ever reach the function.
4. Redeploy and confirm `/api/health` shows `"audio_ready": true` and
   `"vision_ready": false`.

### Visual: not possible on Vercel

Two independent blockers, either one fatal:

- **Request body.** A camera recording is far larger than 4.5 MB - a 22 s
  640x480 clip is 6.7 MB, a 60 s 720p clip is 143 MB. The video cannot reach
  the function at all.
- **Bundle.** opencv + openvino + ultralytics + torch measures ~1.7 GB, plus
  ~58 MB of model weights. That needs the Large Functions beta (5 GB), and
  even then there is no GPU or NPU: measured on an Intel Core Ultra 7 255H,
  a 60 s 720p clip takes 12.9 s on the iGPU but 33.7 s on CPU.

If you want visual analysis against a public frontend, the backend has to be
something other than a serverless function - a long-running container (Render,
Railway, Fly.io, Hugging Face Spaces) or your own Intel machine exposed through
a tunnel. Only the latter gets the NPU/GPU numbers in `backend/BENCHMARKS.md`.

Running `start.bat` locally gives you the complete feature set with no limits.

## Full Audio/Vision note

The local build can run the complete Phase 20 OpenVINO Audio + Vision analyzer by setting `LOCAL_SCORING_ENABLED=true` and installing `requirements-local.txt`. The current Vercel public backend is intentionally the lightweight Cloudflare deployment, so it does not run the native OpenVINO analyzer. A public deployment of Phase 20 Audio/Vision requires a separate long-running compute backend or a browser/local-companion architecture rather than the current Vercel serverless backend.
