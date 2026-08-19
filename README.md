# Clarivo — public deploy-ready MVP

Clarivo is the renamed public MVP of the explanation coach. The current flow is:

1. Record an English explanation or paste a transcript.
2. Cloudflare Whisper creates the transcript.
3. Review/edit the transcript.
4. Add the session to the browser queue.
5. Cloudflare Qwen analyzes the content using the preserved evaluator prompt/schema.
6. Completed sessions stay in the browser; raw audio is stored locally in IndexedDB for future Delivery analysis.

## Local run

Backend:

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
notepad .env
.\.venv\Scripts\python.exe -m uvicorn main:app --reload --port 8000
```

Frontend:

```powershell
cd frontend
npm.cmd install
npm.cmd run dev
```

Open `http://localhost:5173`.

For public deployment, read `DEPLOY_PUBLIC.md`.
