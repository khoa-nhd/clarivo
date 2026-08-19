@echo off
if not exist .venv\Scripts\python.exe (
  echo Missing backend .venv. Run: python -m venv .venv
  pause
  exit /b 1
)
.venv\Scripts\python.exe -m uvicorn main:app --reload --port 8000
