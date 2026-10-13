@echo off
rem Starts SyncViewer locally: generator, API, collector and frontend, each in its own window.
rem Close a window (or press Ctrl+C in it) to stop that service.
setlocal
set "ROOT=%~dp0"
set "PY=%ROOT%backend\.venv\Scripts\python.exe"

if not exist "%ROOT%.env" (
  echo .env is missing. Copy .env.example to .env and fill it in first.
  pause & exit /b 1
)
if not exist "%PY%" (
  echo Python environment not found at backend\.venv. Create it and install the backend first.
  pause & exit /b 1
)
if not exist "%ROOT%frontend\node_modules" (
  echo Installing frontend packages, this happens once...
  pushd "%ROOT%frontend" && call npm install && popd
)

netstat -ano | findstr /r /c:":8000 .*LISTENING" >nul && (
  echo Port 8000 is already in use by another program. Stop it, then run this again.
  pause & exit /b 1
)

rem cmd /k keeps each window open if a service stops, so its error stays readable
start "SyncViewer - Generator (8100)" /D "%ROOT%generator" cmd /k ""%PY%" -m uvicorn syncgen.main:app --port 8100"
start "SyncViewer - API (8000)" /D "%ROOT%backend" cmd /k ""%PY%" -m uvicorn app.main:create_app --factory --port 8000"
rem give the generator and API a moment before the first collection cycle
timeout /t 5 /nobreak >nul
start "SyncViewer - Collector" /D "%ROOT%backend" cmd /k ""%PY%" -m app.collector.serve"
start "SyncViewer - Frontend (5173)" /D "%ROOT%frontend" cmd /k npm run dev

echo Waiting for the frontend to start...
timeout /t 8 /nobreak >nul
start "" http://localhost:5173
echo SyncViewer is running. Close the four service windows to stop it.
timeout /t 5 >nul
