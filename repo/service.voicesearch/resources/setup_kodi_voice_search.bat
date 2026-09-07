@echo off
setlocal enabledelayedexpansion

REM =========================================================
REM Kodi Voice Search - setup_kodi_voice_search.bat
REM Version: 1.3.6
REM =========================================================
REM =========================================================
REM Usage:
REM   setup_kodi_voice_search.bat                  -> interactive (double-click)
REM   setup_kodi_voice_search.bat silent "<dir>"    -> unattended, called by
REM                                                     the Kodi service addon.
REM                                                     <dir> is the addon's
REM                                                     userdata folder, where
REM                                                     python_path.txt and
REM                                                     setup_log.txt are written.
REM
REM All packages are installed into an ISOLATED virtual environment at
REM %LOCALAPPDATA%\KodiVoiceSearch\venv -- your existing Python install
REM (if any) is only used as a template to create it, and is never
REM itself modified. This is deliberate: it means this project can
REM never conflict with, upgrade a dependency of, or otherwise affect
REM whatever else you use Python for on this PC. Uninstalling later is
REM just deleting that one folder.
REM =========================================================

set "SILENT=%~1"
set "PROFILE_DIR=%~2"

REM Ensure the profile dir exists regardless of silent/interactive
REM mode -- both python_path.txt (Step 4) and, in silent mode, the log
REM file below need it to exist. In practice service.py's own
REM ensure_config_exists() already creates this before either entry
REM point can run, but don't rely on that ordering here.
if not "!PROFILE_DIR!"=="" (
    if not exist "!PROFILE_DIR!" mkdir "!PROFILE_DIR!" >nul 2>nul
)

if /I "%SILENT%"=="silent" (
    set "LOGFILE=%PROFILE_DIR%\setup_log.txt"
    call :main > "!LOGFILE!" 2>&1
    exit /b !errorlevel!
) else (
    call :main
    exit /b !errorlevel!
)

:main
echo ============================================
echo  Kodi Voice Search - Windows Setup
echo  Run at: %date% %time%
echo ============================================
echo.
echo This will:
echo   1. Install Python (only if it is not already installed)
echo   2. Create an isolated virtual environment just for this project
echo      ^(your existing Python install, if any, is never modified^)
echo   3. Install packages for BOTH supported speech engines into it:
echo        - Windows Speech Recognition ^(SAPI / pywin32^)
echo        - Google Speech API ^(SpeechRecognition + pyaudio^)
echo.

if /I not "%SILENT%"=="silent" pause

REM =========================================================
REM Step 1: Find a base Python to build the virtual environment from
REM (only used as a template -- never itself modified)
REM
REM IMPORTANT: Windows 10/11 ships a FAKE python.exe on PATH by
REM default (an "App execution alias" at
REM ...\AppData\Local\Microsoft\WindowsApps\python.exe) that exists
REM purely to redirect you to the Microsoft Store if you type "python"
REM with nothing real installed. "where python" finds this fake file
REM just fine and reports success -- it is NOT a real interpreter, and
REM trying to use it fails every command run against it. So we check
REM what "python --version" actually PRINTS, not just whether some
REM file named python.exe exists on PATH.
REM =========================================================
set "REAL_PYTHON_FOUND=0"
set "PYTHON_CMD="

where python >nul 2>nul
if %errorlevel% equ 0 (
    for /f "delims=" %%V in ('python --version 2^>^&1') do (
        echo %%V | findstr /R "^Python [0-9]" >nul
        if not errorlevel 1 set "REAL_PYTHON_FOUND=1"
    )
)

if "!REAL_PYTHON_FOUND!"=="0" (
    echo.
    echo Python was not found ^(or only the Windows Store placeholder is
    echo present on PATH -- this is a known Windows quirk, not a real
    echo Python install^). Downloading and installing a real Python now...
    echo ^(Pinned to Python 3.13.15, the latest stable release as of this script's
    echo  writing. If this link is dead by the time you run it, download the
    echo  latest installer yourself from https://www.python.org/downloads/windows/^)
    echo.

    set "PYTHON_URL=https://www.python.org/ftp/python/3.13.15/python-3.13.15-amd64.exe"
    set "INSTALLER=%TEMP%\python_installer.exe"

    powershell -NoProfile -Command "try { Invoke-WebRequest -Uri '!PYTHON_URL!' -OutFile '!INSTALLER!' } catch { exit 1 }"

    if not exist "!INSTALLER!" (
        echo.
        echo ERROR: Failed to download the Python installer.
        echo Check your internet connection, or install Python manually from
        echo https://www.python.org/downloads/windows/ and re-run this script.
        if /I not "%SILENT%"=="silent" pause
        exit /b 1
    )

    echo Installing Python silently ^(user-level install, no admin needed^)...
    "!INSTALLER!" /quiet InstallAllUsers=0 PrependPath=1 Include_test=0

    echo Waiting for the installer to finish...
    timeout /t 20 /nobreak >nul

    del "!INSTALLER!" >nul 2>nul

    REM This SAME cmd.exe process still has the OLD PATH (Windows only
    REM updates PATH for NEW processes), so we can't rely on "where
    REM python" right here even though it's now installed. We know
    REM exactly where a user-level 3.13.15 install lands.
    set "PYTHON_CMD=%LOCALAPPDATA%\Programs\Python\Python313\python.exe"

    if not exist "!PYTHON_CMD!" (
        echo.
        echo ERROR: Expected Python at !PYTHON_CMD! but it was not found.
        echo The installer may have used a different location. Install
        echo Python manually and re-run this script.
        if /I not "%SILENT%"=="silent" pause
        exit /b 1
    )

    echo.
    echo Python installed at: !PYTHON_CMD!
) else (
    echo Python is already installed:
    python --version

    for /f "delims=" %%P in ('where python 2^>nul') do (
        if not defined PYTHON_CMD set "PYTHON_CMD=%%P"
    )
)

REM =========================================================
REM Step 2: Create (or reuse) an isolated virtual environment.
REM Everything from here on installs into THIS, never into the
REM base Python found/installed above.
REM =========================================================
set "VENV_DIR=%LOCALAPPDATA%\KodiVoiceSearch\venv"
set "VENV_PYTHON=!VENV_DIR!\Scripts\python.exe"
set "PYEXE=!VENV_DIR!\Scripts\pythonw.exe"

if exist "!VENV_PYTHON!" (
    echo.
    echo Reusing existing virtual environment at !VENV_DIR!
) else (
    echo.
    echo Creating an isolated virtual environment at !VENV_DIR!
    echo ^(this keeps these packages completely separate from whatever
    echo  else you use Python for on this PC^)...
    "!PYTHON_CMD!" -m venv "!VENV_DIR!"

    if not exist "!VENV_PYTHON!" (
        echo.
        echo ERROR: Failed to create the virtual environment.
        if /I not "%SILENT%"=="silent" pause
        exit /b 1
    )
)

REM =========================================================
REM Step 3: Install packages -- into the venv only
REM =========================================================
echo.
echo Upgrading pip inside the virtual environment...
"!VENV_PYTHON!" -m pip install --upgrade pip

echo.
echo Installing core dependencies used by both watcher scripts...
"!VENV_PYTHON!" -m pip install websocket-client requests
if %errorlevel% neq 0 (
    echo.
    echo ERROR: Failed to install core dependencies. See the message above.
    if /I not "%SILENT%"=="silent" pause
    exit /b 1
)

echo.
echo Installing Windows Speech Recognition dependencies ^(pywin32^)...
"!VENV_PYTHON!" -m pip install pywin32

REM pywin32 sometimes needs an explicit post-install step to register
REM its COM components correctly inside a venv. Run it if present;
REM harmless if not needed.
if exist "!VENV_DIR!\Scripts\pywin32_postinstall.py" (
    echo Running pywin32 post-install registration...
    "!VENV_PYTHON!" "!VENV_DIR!\Scripts\pywin32_postinstall.py" -install >nul 2>&1
)

echo.
echo Installing Google speech dependencies ^(SpeechRecognition, pyaudio^)...
"!VENV_PYTHON!" -m pip install SpeechRecognition
"!VENV_PYTHON!" -m pip install pyaudio
if %errorlevel% neq 0 (
    echo.
    echo pyaudio failed to install directly. Trying the pipwin fallback...
    "!VENV_PYTHON!" -m pip install pipwin
    "!VENV_PYTHON!" -m pipwin install pyaudio
)

REM =========================================================
REM Step 4: Report the resolved Python path back to Kodi
REM
REM IMPORTANT: this must NOT be gated behind "silent" mode. The manual
REM troubleshooting entry point (setup.py, run from Program Add-ons)
REM runs this script interactively -- visible console, no "silent"
REM arg -- specifically to fix a failed automatic setup. If this write
REM only happened in silent mode, a successful manual fix still
REM wouldn't leave behind the file service.py needs to actually find
REM Python afterward, defeating the entire point of the manual fix.
REM This only needs a profile dir to have been passed at all, silent
REM or not.
REM =========================================================
if not "!PROFILE_DIR!"=="" (
    > "!PROFILE_DIR!\python_path.txt" echo !PYEXE!
    echo.
    echo Wrote resolved Python path to !PROFILE_DIR!\python_path.txt
)

echo.
echo ============================================
echo  Setup complete - both engines installed
echo  Virtual environment: !VENV_DIR!
echo  Your original Python install was not modified.
echo ============================================
echo.
echo If you plan to use Windows Speech Recognition, open it once from
echo the Start menu to finish its mic setup.
echo.
if /I not "%SILENT%"=="silent" pause
exit /b 0
