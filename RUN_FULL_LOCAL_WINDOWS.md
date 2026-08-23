# Run Clarivo with Content + Voice + Visual on Windows

This build combines the existing public Clarivo content evaluator with the uploaded **local scoring v11** audio/vision engine.

## What runs where

- **Content feedback:** Cloudflare Qwen (same as the current Clarivo public build)
- **Transcript:** Cloudflare Whisper (same as the current Clarivo public build)
- **Voice + Visual scoring:** local Intel/OpenVINO backend on your laptop
- **Raw camera/audio media:** stored in the browser on the same device and uploaded only to your local backend for delivery scoring

The Vercel backend intentionally keeps `LOCAL_SCORING_ENABLED=false`; the OpenVINO/YOLO dependencies and model files are too heavy for the current free serverless deployment. The full three-part demo is therefore run locally on the Intel laptop.

## 1. Backend setup (first time only)

Open PowerShell in `backend`:

```powershell
python -m venv .venv
```

Install Clarivo + local scoring dependencies:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-local.txt
```

Download/export the local vision models:

```powershell
.\.venv\Scripts\python.exe -m local_scoring.setup_delivery_models
```

This downloads only the models needed for the web delivery pipeline: face detection, head pose, facial landmarks, gaze and YOLO pose. It does **not** download the old local Whisper model because Clarivo already uses the web transcript.

## 2. Backend `.env`

If `.env` does not exist:

```powershell
Copy-Item .env.example .env
```

Open it:

```powershell
notepad .env
```

Use your real Cloudflare credentials and enable local scoring:

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
```

Leaving `LOCAL_MODELS_DIR` blank uses `backend/local_scoring/models` automatically.

## 3. Start backend

```powershell
.\.venv\Scripts\python.exe -m uvicorn main:app --reload --port 8000
```

Open:

```text
http://127.0.0.1:8000/api/health
```

Check that the response contains:

```json
"delivery_analysis": {
  "enabled": true,
  "models_ready": true,
  "mode": "local_openvino"
}
```

## 4. Frontend setup (first time only)

Open a second PowerShell in `frontend`:

```powershell
npm.cmd install
```

## 5. Start frontend

```powershell
npm.cmd run dev
```

Open:

```text
http://localhost:5173
```

## 6. Use it

1. Enter topic and audience.
2. Click **Start recording**.
3. Allow both camera and microphone.
4. Present normally.
5. Click **Stop & transcribe**.
6. Review/edit the transcript.
7. Click **Add to analysis queue**.
8. Clarivo runs content analysis and local v11 Voice + Visual analysis.
9. The report intentionally shows only a compact set of metrics:
   - Voice score, pace, pauses, audibility, filler count only when reliable
   - Visual score, attention, posture, gesture level
   - up to three delivery priorities

## Every later run

Backend terminal:

```powershell
cd backend
.\.venv\Scripts\python.exe -m uvicorn main:app --reload --port 8000
```

Frontend terminal:

```powershell
cd frontend
npm.cmd run dev
```

You do not need to reinstall packages or models every time.
