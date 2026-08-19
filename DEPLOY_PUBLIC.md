# Deploy Clarivo publicly for $0 under free-tier limits

This setup uses one GitHub repository and **two Vercel projects**:

- `frontend/` → Clarivo website
- `backend/` → Clarivo FastAPI API

Cloudflare Workers AI runs Qwen and Whisper. No Cloudflare secret is placed in the frontend.

## 0. Before deployment

Confirm local mode works with real Cloudflare AI:

- `http://127.0.0.1:8000/api/health` shows `provider: cloudflare` and `transcription_provider: cloudflare`.
- Record → transcribe → edit → queue → feedback works locally.

## 1. Push the project to GitHub

Create a new empty GitHub repository, for example `clarivo`. In the project root:

```powershell
git init
git add .
git commit -m "Clarivo public MVP"
git branch -M main
git remote add origin YOUR_GITHUB_REPOSITORY_URL
git push -u origin main
```

`backend/.env` is ignored by `.gitignore`. Never upload your Cloudflare token.

## 2. Deploy the backend first

In Vercel:

1. Add New → Project.
2. Import the GitHub repository.
3. Set **Root Directory** to `backend`.
4. Leave framework auto-detection/defaults. Vercel recognizes `index.py` as the FastAPI entry point.
5. Add these Environment Variables for Production:

```text
AI_PROVIDER=cloudflare
TRANSCRIPTION_PROVIDER=cloudflare
CLOUDFLARE_ACCOUNT_ID=<your real account id>
CLOUDFLARE_AUTH_TOKEN=<your real Workers AI token>
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
```

6. Deploy.
7. Copy the production URL, for example `https://clarivo-api.vercel.app`.
8. Open `https://YOUR-BACKEND/api/health`. It should report Cloudflare for both AI and transcription.

## 3. Deploy the frontend

Create a **second Vercel project** from the same GitHub repository:

1. Add New → Project.
2. Import the same repository.
3. Set Root Directory to `frontend`.
4. Add this Production Environment Variable:

```text
VITE_API_BASE_URL=https://YOUR-BACKEND.vercel.app
```

Do not add `/api` and do not add a trailing slash.

5. Deploy.
6. Copy the frontend URL, for example `https://clarivo.vercel.app`.

## 4. Lock backend CORS to the frontend

Return to the **backend** Vercel project and set:

```text
ALLOWED_ORIGINS=https://YOUR-FRONTEND.vercel.app
```

Save and redeploy the backend.

## 5. Test from a different machine

Open only the frontend URL on another computer (preferably current Chrome/Edge):

1. Allow microphone access.
2. Record 20–30 seconds.
3. Stop & transcribe.
4. Edit the transcript if needed.
5. Add to queue.
6. Confirm the Qwen report completes.
7. Create a second session while the first analyzes.

The other computer needs no Python, Node.js, Ollama, Cloudflare account, or API token.

## Important free-tier behavior

- Vercel Hobby is intended for personal/non-commercial projects and has usage caps.
- Workers AI has a daily free allocation. If it is exhausted, Clarivo shows a retry/daily-limit message instead of exposing raw credentials.
- Recording is capped at 5 minutes and compressed to keep uploads comfortably below Vercel Function payload limits.
- Sessions and raw audio are browser-local; they do not sync between devices.
