@echo off
setlocal
if not exist .venv\Scripts\python.exe (
  echo Creating Python virtual environment...
  python -m venv .venv
)
.venv\Scripts\python.exe -m pip install --upgrade pip
.venv\Scripts\python.exe -m pip install -r requirements-local.txt
.venv\Scripts\python.exe -m local_scoring.setup_delivery_models

echo.
echo Local Clarivo Voice + Visual dependencies are ready.
pause
