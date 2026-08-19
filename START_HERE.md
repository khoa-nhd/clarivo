# Clarivo — START HERE

## Local

### Backend
```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
notepad .env
.\.venv\Scripts\python.exe -m uvicorn main:app --reload --port 8000
```

Fill your real Cloudflare Account ID and Workers AI token in `backend/.env`.

### Frontend
```powershell
cd frontend
npm.cmd install
npm.cmd run dev
```

Open `http://localhost:5173`.

## Public
Read `DEPLOY_PUBLIC.md`.
