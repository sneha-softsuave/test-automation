@echo off
echo Starting Deep Agent Development Servers...
echo.

:: Start Backend
echo [1/2] Starting Backend API (port 8000)...
start "Deep Agent - Backend" cmd /k "cd /d %~dp0 && venv\Scripts\activate && python run.py"

:: Wait for backend to start
timeout /t 3 /nobreak > nul

:: Start Frontend
echo [2/2] Starting Frontend (port 3000)...
start "Deep Agent - Frontend" cmd /k "cd /d %~dp0frontend && npm run dev"

echo.
echo ================================
echo Deep Agent is starting up!
echo.
echo Backend API:  http://localhost:8000
echo Frontend UI:  http://localhost:3000
echo ================================
echo.
echo Press any key to close this window...
pause > nul
