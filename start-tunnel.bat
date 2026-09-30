@echo off
chcp 65001 >nul
setlocal EnableDelayedExpansion
title Clarivo - AI tunnel
cd /d "%~dp0"

set "ROOT=%CD%"
set "VENV_PY=%ROOT%\backend\.venv\Scripts\python.exe"
set "PORT=8000"

REM  PYTHONIOENCODING: mot ky tu khong ma hoa duoc trong log (vi du emoji)
REM  se nem UnicodeEncodeError tren console Windows (cp1252) va lam HONG
REM  request dang xu ly. Ep UTF-8 de dieu do khong the xay ra.
set "PYTHONIOENCODING=utf-8"

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
REM  3. Mo duong ham va tu ghep link chia se
REM
REM     Dia chi quick tunnel doi moi lan chay. Frontend doc dia chi nay LUC
REM     CHAY (tham so ?ai= tren link), khong phai luc build - nen doi dia chi
REM     chi can gui link moi, KHONG can build lai tren Vercel.
REM ----------------------------------------------------------------------
echo  [2/2] Mo duong ham Cloudflare...
if exist "%ROOT%\tunnel.log" del "%ROOT%\tunnel.log" >nul 2>&1
start "Clarivo tunnel" cmd /k "cloudflared tunnel --url http://127.0.0.1:%PORT% --logfile ""%ROOT%\tunnel.log"""

echo  Dang doi cloudflared cap dia chi...
pushd "%ROOT%\backend"
"%VENV_PY%" -m tools.share_link --log "%ROOT%\tunnel.log" --out "%ROOT%\SHARE_LINK.txt"
popd

echo   May nay phai MO va KHONG NGU thi phan Giong noi / Hinh anh
echo   moi hoat dong. Dong 2 cua so vua hien ra la tat het.
echo.
pause
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
