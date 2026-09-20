@echo off
chcp 65001 >nul
setlocal EnableDelayedExpansion
title Clarivo - AI tunnel
cd /d "%~dp0"

set "ROOT=%CD%"
set "VENV_PY=%ROOT%\backend\.venv\Scripts\python.exe"
set "PORT=8000"

echo.
echo  ==========================================
echo    CLARIVO - mo backend AI ra internet
echo  ==========================================
echo.
echo  Script nay bat backend AI cuc bo (giong start.bat)
echo  roi mo mot duong ham Cloudflare de trang Vercel
echo  goi vao duoc.
echo.
echo  Trang Vercel van chay binh thuong khi script nay tat;
echo  chi phan Giong noi / Hinh anh la tam thoi khong dung duoc.
echo.

REM ----------------------------------------------------------------------
REM  1. Kiem tra moi truong
REM ----------------------------------------------------------------------
if not exist "%VENV_PY%" goto :no_venv

"%VENV_PY%" -c "import openvino, cv2, ultralytics, librosa" >nul 2>&1
if not %errorlevel%==0 goto :no_local_ai

if not exist "%ROOT%\backend\local_scoring\models\face" goto :no_models

where cloudflared >nul 2>&1
if not %errorlevel%==0 goto :no_cloudflared

REM ----------------------------------------------------------------------
REM  2. Bat backend AI
REM     --reload bi tat: day la che do phuc vu cong khai, khong phai dev.
REM ----------------------------------------------------------------------
echo  [1/2] Bat backend AI tren cong %PORT%...
start "Clarivo AI backend - port %PORT%" /D "%ROOT%\backend" cmd /k ".venv\Scripts\python.exe -m uvicorn main:app --port %PORT% --host 127.0.0.1"

set /a tries=0
:wait_backend
set /a tries+=1
curl -s -o nul --max-time 2 http://127.0.0.1:%PORT%/api/health >nul 2>&1
if not errorlevel 1 goto :backend_up
if %tries% GEQ 60 goto :backend_timeout
ping -n 2 127.0.0.1 >nul
goto :wait_backend
:backend_up

REM ----------------------------------------------------------------------
REM  3. Mo duong ham
REM ----------------------------------------------------------------------
echo  [2/2] Mo duong ham Cloudflare...
echo.
echo  ------------------------------------------------------------------
echo   TIM DONG CO DANG:  https://....trycloudflare.com
echo   trong cua so "Clarivo tunnel" vua hien ra.
echo.
echo   Do la dia chi backend AI cua ban.
echo  ------------------------------------------------------------------
echo.
echo   LUU Y QUAN TRONG:
echo   - Dia chi nay DOI MOI LAN chay (quick tunnel).
echo     Doi mot lan la phai build lai frontend tren Vercel.
echo     Muon dia chi co dinh, dung named tunnel - xem
echo     DEPLOY_TUNNEL.md muc "Duong ham co dinh".
echo.
echo   - Sau khi co dia chi, dat vao Vercel (frontend):
echo         VITE_LOCAL_AI_BASE_URL=https://...trycloudflare.com
echo     va vao backend\.env tren may nay:
echo         ALLOWED_ORIGINS=https://ten-frontend.vercel.app
echo.
echo   - May nay phai MO va KHONG NGU thi phan Giong noi/Hinh anh
echo     moi hoat dong.
echo.

start "Clarivo tunnel" cmd /k "cloudflared tunnel --url http://127.0.0.1:%PORT%"

echo  Da mo 2 cua so. Dong chung lai la tat.
echo.
ping -n 6 127.0.0.1 >nul
exit /b 0

REM ----------------------------------------------------------------------
:no_venv
echo  [LOI] Chua co backend\.venv.
echo        Chay start.bat truoc de tao moi truong.
echo.
pause
exit /b 1

:no_local_ai
echo  [LOI] Thieu thu vien AI cuc bo (openvino / opencv / ultralytics / librosa).
echo        Chay:  backend\setup_local_scoring.bat
echo.
pause
exit /b 1

:no_models
echo  [LOI] Chua tai model OpenVINO.
echo        Chay:  backend\setup_local_scoring.bat
echo        Hoac:  backend\.venv\Scripts\python.exe -m local_scoring.setup_delivery_models
echo.
pause
exit /b 1

:no_cloudflared
echo  [LOI] Chua cai cloudflared.
echo.
echo        Cai bang lenh nay (mo PowerShell):
echo            winget install --id Cloudflare.cloudflared
echo.
echo        Roi mo lai cua so nay va chay lai file.
echo.
pause
exit /b 1

:backend_timeout
echo.
echo  [LOI] Backend khong phan hoi sau 60 giay.
echo        Xem cua so "Clarivo AI backend" de biet loi.
echo.
pause
exit /b 1
