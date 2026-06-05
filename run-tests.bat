@echo off
setlocal
cd /d "%~dp0"

where python >nul 2>nul
if errorlevel 1 (
  echo [ERROR] Python was not found in PATH.
  pause
  exit /b 1
)

set PYTHONPATH=src
echo Running tests...
python -m pytest -q
set EXIT_CODE=%ERRORLEVEL%
if not "%EXIT_CODE%"=="0" (
  echo.
  echo Tests failed with code %EXIT_CODE%.
  pause
  exit /b %EXIT_CODE%
)

echo.
echo Running CLI smoke checks...
python -m pp_agent.cli.main --help
python -m pp_agent.cli.main config show
pause
exit /b 0
