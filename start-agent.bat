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

set "PYTHONPATH=%CD%\src"
if "%PP_AGENT_API_KEY%"=="" (
  echo [WARN] PP_AGENT_API_KEY is not set.
  echo You can still open the CLI, but model requests will fail until you set it.
  echo Example:
  echo   set PP_AGENT_API_KEY=your_api_key
  echo.
)

python -c "import httpx, prompt_toolkit, pydantic, rich, typer, chromadb" >nul 2>nul
if errorlevel 1 (
  echo [INFO] Missing one or more core dependencies. Attempting to install main package dependencies...
  python -m pip install --default-timeout 180 .
  if errorlevel 1 (
    echo [ERROR] Failed to install required dependencies automatically.
    echo This usually means your network is too slow or pip is too old for this environment.
    echo Try one of these commands:
    echo   python -m pip install --default-timeout 180 .
    echo   python -m pip install --upgrade pip setuptools wheel
    echo Then run start-agent.bat again.
    pause
    exit /b 1
  )
  echo.
)



echo           _____                    _____                    _____                    _____                    _____                   _______
echo          /\    \                  /\    \                  /\    \                  /\    \                  /\    \                 /::\    \
echo         /::\    \                /::\    \                /::\    \                /::\    \                /::\____\               /::::\    \
echo        /::::\    \              /::::\    \              /::::\    \              /::::\    \              /:::/    /              /::::::\    \
echo       /::::::\    \            /::::::\    \            /::::::\    \            /::::::\    \            /:::/    /              /::::::::\    \
echo      /:::/\:::\    \          /:::/\:::\    \          /:::/\:::\    \          /:::/\:::\    \          /:::/    /              /:::/~~\:::\    \
echo     /:::/__\:::\    \        /:::/__\:::\    \        /:::/__\:::\    \        /:::/  \:::\    \        /:::/____/              /:::/    \:::\    \
echo    /::::\   \:::\    \      /::::\   \:::\    \      /::::\   \:::\    \      /:::/    \:::\    \      /::::\    \             /:::/    / \:::\    \
echo   /::::::\   \:::\    \    /::::::\   \:::\    \    /::::::\   \:::\    \    /:::/    / \:::\    \    /::::::\    \   _____   /:::/____/   \:::\____\
echo  /:::/\:::\   \:::\____\  /:::/\:::\   \:::\____\  /:::/\:::\   \:::\    \  /:::/    /   \:::\    \  /:::/\:::\    \ /\    \ ^|:::^|    ^|     ^|:::^|    ^|
echo /:::/  \:::\   \:::^|    ^|/:::/  \:::\   \:::^|    ^|/:::/__\:::\   \:::\____\/:::/____/     \:::\____\/:::/  \:::\    /::\____\^|:::^|____^|     ^|:::^|    ^|
echo \::/    \:::\  /:::^|____^|\::/    \:::\  /:::^|____^|\:::\   \:::\   \::/    /\:::\    \      \::/    /\::/    \:::\  /:::/    / \:::\    \   /:::/    /
echo  \/_____/\:::\/:::/    /  \/_____/\:::\/:::/    /  \:::\   \:::\   \/____/  \:::\    \      \/____/  \/____/ \:::\/:::/    /   \:::\    \ /:::/    /
echo          \::::::/    /            \::::::/    /    \:::\   \:::\    \       \:::\    \                       \::::::/    /     \:::\    /:::/    /
echo           \::::/    /              \::::/    /      \:::\   \:::\____\       \:::\    \                       \::::/    /       \:::\__/:::/    /
echo            \::/____/                \::/____/        \:::\   \::/    /        \:::\    \                      /:::/    /         \::::::::/    /
echo             ~~                       ~~               \:::\   \/____/          \:::\    \                    /:::/    /           \::::::/    /
echo                                                        \:::\    \               \:::\    \                  /:::/    /             \::::/    /
echo                                                         \:::\____\               \:::\____\                /:::/    /               \::/____/
echo                                                          \::/    /                \::/    /                \::/    /                 ~~
echo                                                           \/____/                  \/____/                  \/____/
echo.

echo Starting pp-agent chat...
python -m agent_cli.main chat
set EXIT_CODE=%ERRORLEVEL%
if not "%EXIT_CODE%"=="0" (
  echo.
  echo pp-agent exited with code %EXIT_CODE%.
)
pause
exit /b %EXIT_CODE%
