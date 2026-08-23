# Clarivo — Full Content + Audio + Vision analysis on Windows

This build does **real analysis**, not only capture:

- Content: Cloudflare Qwen3
- Transcript: Cloudflare Whisper
- Voice: local v11 audio scorer
- Visual: local OpenVINO v11 vision scorer

The recording is captured once. After you review the transcript and add the session to the queue, Clarivo runs Content, Voice and Visual analysis for that same session.

## 1. Backend setup

Open PowerShell in `backend`.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-local.txt
```

Download the OpenVINO vision models:

```powershell
.\.venv\Scripts\python.exe -m local_scoring.setup_delivery_models
```

Create `.env`:

```powershell
Copy-Item .env.example .env
notepad .env
```

Use:

```env
AI_PROVIDER=cloudflare
TRANSCRIPTION_PROVIDER=cloudflare

CLOUDFLARE_ACCOUNT_ID=YOUR_REAL_ACCOUNT_ID
CLOUDFLARE_AUTH_TOKEN=YOUR_REAL_API_TOKEN

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
```

Run:

```powershell
.\.venv\Scripts\python.exe -m uvicorn main:app --reload --port 8000
```

Open:

```text
http://127.0.0.1:8000/api/health
```

Look for:

```json
"delivery_analysis": {
  "enabled": true,
  "audio_ready": true,
  "vision_ready": true,
  "models_ready": true,
  "mode": "local_openvino"
}
```

If `vision_ready` is false, rerun the model setup command.

## 2. Frontend setup

Open a second PowerShell in `frontend`.

```powershell
npm.cmd install
npm.cmd run dev
```

Open:

```text
http://localhost:5173
```

## 3. Test flow

1. Enter topic and audience.
2. Click **Start recording**.
3. Allow both camera and microphone.
4. Speak for 20–30 seconds while staying in frame.
5. Click **Stop & transcribe**.
6. Review/edit the transcript.
7. Click **Add to analysis queue**.
8. Clarivo runs these independently:
   - Content → Qwen
   - Voice → v11 audio scorer
   - Visual → v11 OpenVINO vision scorer
9. Open the completed session. The report shows only the compact useful metrics.

## Important architecture note

Voice and Visual are now separate jobs. If camera/vision fails, Voice still finishes. If audio analysis fails, Visual can still finish. Content does not depend on either delivery analyzer.

## Public Vercel note

The Qwen/Whisper portion can run on the current Vercel + Cloudflare public deployment. The local OpenVINO v11 scorer is intentionally designed for a local Intel machine and is not suitable for the lightweight Vercel backend as-is because it requires native OpenVINO/Ultralytics dependencies and model files.
