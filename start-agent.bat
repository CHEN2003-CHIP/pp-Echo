@echo off
setlocal
cd /d "%~dp0"

where python >nul 2>nul
if errorlevel 1 (
  echo [ERROR] Python was not found in PATH.
  echo Please install Python 3.9+ and try again.
  pause
  exit /b 1
)

set PYTHONPATH=src
if "%PP_AGENT_API_KEY%"=="" (
  echo [WARN] PP_AGENT_API_KEY is not set.
  echo You can still open the CLI, but model requests will fail until you set it.
  echo Example:
  echo   set PP_AGENT_API_KEY=your_api_key
  echo.
)

echo Starting pp-agent chat...
python -m agent_cli.main chat
set EXIT_CODE=%ERRORLEVEL%
if not "%EXIT_CODE%"=="0" (
  echo.
  echo pp-agent exited with code %EXIT_CODE%.
)
pause
exit /b %EXIT_CODE%