# Run Clarivo locally on Windows

Open two VS Code terminals.

## Terminal 1 — backend

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
notepad .env
.\.venv\Scripts\python.exe -m uvicorn main:app --reload --port 8000
```

You only create `.venv`, install requirements, and create `.env` the first time.
On later runs you normally only need the final `uvicorn` command.

## Terminal 2 — frontend

```powershell
cd frontend
npm.cmd install
npm.cmd run dev
```

You only need `npm.cmd install` the first time or after dependencies change.
Open `http://localhost:5173`.
