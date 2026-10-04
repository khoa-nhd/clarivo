@echo off
setlocal
if not exist .venv\Scripts\python.exe (
  echo Creating Python virtual environment...
  python -m venv .venv
)
.venv\Scripts\python.exe -m pip install --upgrade pip

echo.
echo [1/3] Installing the runtime dependencies...
.venv\Scripts\python.exe -m pip install -r requirements-local.txt

echo.
echo [2/3] Installing the export-only dependencies (large, removed again below)...
.venv\Scripts\python.exe -m pip install -r requirements-export.txt

echo.
echo [3/3] Downloading and exporting the models...
.venv\Scripts\python.exe -m local_scoring.setup_delivery_models
if not %errorlevel%==0 goto :failed

echo.
echo Removing the export-only dependencies. The models are already exported to
echo OpenVINO IR, and running them needs neither ultralytics nor torch - this is
echo about 550 MB of the install.
.venv\Scripts\python.exe -m pip uninstall -y ultralytics torch torchvision

echo.
echo Local Clarivo Voice + Visual dependencies are ready.
pause
exit /b 0

:failed
echo.
echo [ERROR] Model setup failed. The export dependencies have been left in place
echo         so you can retry with:
echo             .venv\Scripts\python.exe -m local_scoring.setup_delivery_models
pause
exit /b 1
