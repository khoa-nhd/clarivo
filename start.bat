@echo off
chcp 65001 >nul
setlocal
title Clarivo
cd /d "%~dp0"

set "ROOT=%CD%"

REM  PYTHONIOENCODING: mot ky tu khong ma hoa duoc trong log (vi du emoji)
REM  se nem UnicodeEncodeError tren console Windows (cp1252) va lam HONG
REM  request dang xu ly. Ep UTF-8 de dieu do khong the xay ra.
set "PYTHONIOENCODING=utf-8"
set "VENV_PY=%ROOT%\backend\.venv\Scripts\python.exe"

echo.
echo  ==========================================
echo    CLARIVO - dang khoi dong du an
echo  ==========================================
echo.

REM ----------------------------------------------------------------------
REM  1. Tim Python
REM ----------------------------------------------------------------------
set "PY_CMD="
where python >nul 2>&1 && set "PY_CMD=python"
if defined PY_CMD goto :have_python
where py >nul 2>&1 && set "PY_CMD=py -3"
if defined PY_CMD goto :have_python
goto :no_python
:have_python

REM ----------------------------------------------------------------------
REM  2. Tim Node / npm
REM ----------------------------------------------------------------------
where npm >nul 2>&1 || goto :no_node

REM ----------------------------------------------------------------------
REM  3. Moi truong ao Python (.venv)
REM ----------------------------------------------------------------------
if exist "%VENV_PY%" goto :venv_ok
echo [1/5] Tao moi truong Python (.venv) - lan dau se hoi lau mot chut...
%PY_CMD% -m venv "%ROOT%\backend\.venv"
if not exist "%VENV_PY%" goto :venv_fail
:venv_ok

REM ----------------------------------------------------------------------
REM  4. Thu vien backend
REM     Chi cai goi nhe cho web (FastAPI + Cloudflare AI).
REM     Muon chay AI cuc bo bang OpenVINO thi chay:
REM         backend\setup_local_scoring.bat
REM ----------------------------------------------------------------------
"%VENV_PY%" -c "import fastapi, uvicorn, dotenv, multipart" >nul 2>&1
if %errorlevel%==0 goto :deps_ok
echo [2/5] Cai thu vien backend...
"%VENV_PY%" -m pip install --upgrade pip --quiet --disable-pip-version-check
"%VENV_PY%" -m pip install -r "%ROOT%\backend\requirements.txt" --quiet --disable-pip-version-check
if errorlevel 1 goto :deps_fail
:deps_ok

REM ----------------------------------------------------------------------
REM  5. File cau hinh .env
REM ----------------------------------------------------------------------
if exist "%ROOT%\backend\.env" goto :env_ok
echo [3/5] Tao backend\.env tu .env.example (che do mock, khong can API key)...
copy /y "%ROOT%\backend\.env.example" "%ROOT%\backend\.env" >nul
:env_ok

REM ----------------------------------------------------------------------
REM  6. Thu vien frontend
REM ----------------------------------------------------------------------
if exist "%ROOT%\frontend\node_modules" goto :node_ok
echo [4/5] Cai thu vien frontend (npm install)...
pushd "%ROOT%\frontend"
call npm install
popd
if not exist "%ROOT%\frontend\node_modules" goto :npm_fail
:node_ok

REM ----------------------------------------------------------------------
REM  7. Bat 2 server trong 2 cua so rieng
REM ----------------------------------------------------------------------
echo [5/5] Khoi dong server...
echo.
start "Clarivo backend - port 8000" /D "%ROOT%\backend" cmd /k ".venv\Scripts\python.exe -m uvicorn main:app --reload --port 8000"
start "Clarivo frontend - port 5173" /D "%ROOT%\frontend" cmd /k "npm run dev"

REM ----------------------------------------------------------------------
REM  8. Cho 2 server san sang roi mo trinh duyet
REM
REM     Dung "localhost" chu khong phai "127.0.0.1" cho frontend:
REM     Vite lang nghe tren ::1 (IPv6), nen dia chi IPv4 se khong ket noi duoc.
REM
REM     Dung "ping" thay cho "timeout" de nghi: "timeout" bao loi
REM     "Input redirection is not supported" khi script duoc goi tu mot
REM     tien trinh khong co console rieng.
REM ----------------------------------------------------------------------
echo      Dang cho server san sang...
set /a tries=0
:wait_loop
set /a tries+=1
curl -s -o nul --max-time 2 http://127.0.0.1:8000/api/health >nul 2>&1
if errorlevel 1 goto :wait_next
curl -s -o nul --max-time 2 http://localhost:5173 >nul 2>&1
if not errorlevel 1 goto :ready
:wait_next
if %tries% GEQ 60 goto :timeout
ping -n 2 127.0.0.1 >nul
goto :wait_loop

:ready
start "" http://localhost:5173
echo.
echo  ==========================================
echo    Clarivo dang chay
echo.
echo    Giao dien : http://localhost:5173
echo    Backend   : http://127.0.0.1:8000/api/health
echo.
echo    AI dang o che do MOCK (khong ton quota).
echo    Muon dung AI that: mo backend\.env va dat
echo        AI_PROVIDER=cloudflare
echo        TRANSCRIPTION_PROVIDER=cloudflare
echo        CLOUDFLARE_ACCOUNT_ID=...
echo        CLOUDFLARE_AUTH_TOKEN=...
echo    roi chay lai file nay.
echo.
echo    Tat du an: dong 2 cua so backend va frontend.
echo  ==========================================
echo.
ping -n 9 127.0.0.1 >nul
exit /b 0

:timeout
echo.
echo  [!] Server chua phan hoi sau 60 giay.
echo      Xem 2 cua so "Clarivo backend" va "Clarivo frontend" de biet loi.
echo      Cong 8000 hoac 5173 co the dang bi chuong trinh khac chiem.
echo      Neu 2 cua so van chay binh thuong, cu mo tay:
echo          http://localhost:5173
echo.
pause
exit /b 1

:no_python
echo.
echo  [LOI] Khong tim thay Python.
echo        Cai Python 3.11 tro len tai https://www.python.org/downloads/
echo        Nho tick "Add python.exe to PATH" khi cai.
echo.
pause
exit /b 1

:no_node
echo.
echo  [LOI] Khong tim thay Node.js / npm.
echo        Cai Node.js LTS tai https://nodejs.org/
echo.
pause
exit /b 1

:venv_fail
echo.
echo  [LOI] Khong tao duoc moi truong ao tai backend\.venv
echo        Thu chay thu cong:  python -m venv backend\.venv
echo.
pause
exit /b 1

:deps_fail
echo.
echo  [LOI] Cai thu vien backend that bai.
echo        Kiem tra ket noi mang roi chay lai file nay.
echo.
pause
exit /b 1

:npm_fail
echo.
echo  [LOI] npm install that bai.
echo        Vao thu muc frontend va chay thu cong: npm install
echo.
pause
exit /b 1
