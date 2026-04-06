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
  echo You can still open the TUI, but model requests will fail until you set it.
  echo Example:
  echo   set PP_AGENT_API_KEY=your_api_key
  echo.
)

python -c "import textual" >nul 2>nul
if errorlevel 1 (
  echo [INFO] Textual is not installed. Attempting to install TUI dependencies...
  python -m pip install -e .[tui]
  if errorlevel 1 (
    echo [WARN] Editable install failed. Falling back to a standard install...
    python -m pip install .[tui]
    if errorlevel 1 (
      echo [ERROR] Failed to install TUI dependencies automatically.
      echo Try one of these commands:
      echo   python -m pip install .[tui]
      echo   python -m pip install --upgrade pip setuptools wheel
      echo   python -m pip install -e .[tui]
      pause
      exit /b 1
    )
  )
  echo.
)

echo Starting pp-agent TUI...
python -m pp_agent.cli.main tui
set EXIT_CODE=%ERRORLEVEL%
if not "%EXIT_CODE%"=="0" (
  echo.
  echo pp-agent TUI exited with code %EXIT_CODE%.
)
pause
exit /b %EXIT_CODE%
