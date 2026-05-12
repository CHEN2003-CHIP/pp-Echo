@echo off
setlocal
cd /d "%~dp0"
title pp-Echo Web UI

set "WEB_HOST=127.0.0.1"
set "WEB_PORT=8765"
set "WEB_URL=http://%WEB_HOST%:%WEB_PORT%"
set "WEB_WORKSPACE=%~1"
if "%WEB_WORKSPACE%"=="" set "WEB_WORKSPACE=%CD%"

where python >nul 2>nul
if errorlevel 1 (
  echo [ERROR] Python was not found in PATH.
  echo Please install Python 3.9+ and try again.
  pause
  exit /b 1
)

set "PYTHONPATH=%CD%\src"
if "%PP_AGENT_HTTP_TRUST_ENV%"=="" (
  set "PP_AGENT_HTTP_TRUST_ENV=0"
)
if "%PP_AGENT_API_KEY%"=="" (
  echo [WARN] PP_AGENT_API_KEY is not set.
  echo You can still open the Web UI, but model requests will fail until you set it.
  echo Example:
  echo   set PP_AGENT_API_KEY=your_api_key
  echo.
)

python -c "import fastapi, uvicorn" >nul 2>nul
if errorlevel 1 (
  echo [INFO] Web server dependencies are missing. Installing pp-Echo web dependencies...
  python -m pip install --default-timeout 180 -e .[web]
  if errorlevel 1 (
    echo [WARN] Editable install failed. Falling back to a standard install...
    python -m pip install --default-timeout 180 .[web]
    if errorlevel 1 (
      echo [ERROR] Failed to install Web UI dependencies automatically.
      echo Try one of these commands:
      echo   python -m pip install --default-timeout 180 -e .[web]
      echo   python -m pip install --upgrade pip setuptools wheel
      pause
      exit /b 1
    )
  )
  echo.
)

set "BUILD_WEB=0"
if not exist "web\dist\index.html" set "BUILD_WEB=1"
where npm >nul 2>nul
if not errorlevel 1 set "BUILD_WEB=1"

if "%BUILD_WEB%"=="1" (
  where npm >nul 2>nul
  if errorlevel 1 (
    echo [ERROR] Web UI assets are not built, and npm was not found in PATH.
    echo Please install Node.js 20+ or run the API-only command:
    echo   python -m pp_agent.cli.main web --workspace "%WEB_WORKSPACE%"
    pause
    exit /b 1
  )

  echo [INFO] Building Web UI assets...
  pushd web
  if not exist "node_modules" (
    echo [INFO] Installing frontend dependencies...
    call npm install --cache .npm-cache
    if errorlevel 1 (
      popd
      echo [ERROR] Failed to install frontend dependencies.
      echo If your global npm cache has permission issues, this script already uses web\.npm-cache.
      pause
      exit /b 1
    )
  )

  call npm run build
  if errorlevel 1 (
    popd
    echo [ERROR] Failed to build the Web UI.
    pause
    exit /b 1
  )
  popd
  echo.
)

echo.
echo ============================================
echo   pp-Echo Web UI
echo ============================================
echo Workspace: %WEB_WORKSPACE%
echo URL:       %WEB_URL%
echo.
echo The browser will open automatically.
echo Keep this window open while using the Web UI.
echo Press Ctrl+C to stop the server.
echo.

powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Sleep -Seconds 2; Start-Process '%WEB_URL%'" >nul 2>nul
python -m pp_agent.cli.main web --workspace "%WEB_WORKSPACE%" --host %WEB_HOST% --port %WEB_PORT%
set EXIT_CODE=%ERRORLEVEL%
if not "%EXIT_CODE%"=="0" (
  echo.
  echo pp-Echo Web UI exited with code %EXIT_CODE%.
)
pause
exit /b %EXIT_CODE%
