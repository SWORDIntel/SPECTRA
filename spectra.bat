@echo off
REM SPECTRA Windows Launcher
REM =========================
REM Cross-platform Windows batch file for launching SPECTRA
REM Supports Windows 10/11, PowerShell, and Git Bash environments

setlocal enabledelayedexpansion

REM Color support for Windows 10/11
set "BLUE=[34m"
set "GREEN=[32m"
set "RED=[31m"
set "YELLOW=[33m"
set "CYAN=[36m"
set "WHITE=[37m"
set "NC=[0m"

REM Detect script directory
set "SCRIPT_DIR=%~dp0"
set "PROJECT_ROOT=%SCRIPT_DIR%"

REM Remove trailing backslash
if "%PROJECT_ROOT:~-1%"=="\" set "PROJECT_ROOT=%PROJECT_ROOT:~0,-1%"

echo %CYAN%🚀 SPECTRA Windows Launcher%NC%
echo Platform: Windows

REM Function to find Python
:find_python
set "PYTHON_CMD="

REM Try different Python commands
for %%p in (python3.12 python3.11 python3.10 python3 python py) do (
    %%p --version >nul 2>&1
    if !errorlevel! equ 0 (
        for /f "tokens=2" %%v in ('%%p --version 2^>^&1') do (
            set "version=%%v"
            for /f "tokens=1,2 delims=." %%a in ("!version!") do (
                if %%a geq 3 (
                    if %%b geq 10 (
                        set "PYTHON_CMD=%%p"
                        goto :python_found
                    )
                )
            )
        )
    )
)

echo %RED%✗ Python 3.10+ not found%NC%
echo %YELLOW%Please install Python 3.10 or later from python.org%NC%
pause
exit /b 1

:python_found
echo %GREEN%✓ Python: %PYTHON_CMD%%NC%

REM Check for virtual environment
set "VENV_PYTHON=%PROJECT_ROOT%\.venv\Scripts\python.exe"

if not exist "%VENV_PYTHON%" (
    echo %YELLOW%⚠ Virtual environment not found%NC%
    echo %CYAN%→ Running auto-setup...%NC%

    REM Try to run setup
    if exist "%PROJECT_ROOT%\scripts\spectra_launch.py" (
        "%PYTHON_CMD%" "%PROJECT_ROOT%\scripts\spectra_launch.py" --setup
    ) else (
        echo %RED%✗ Setup script not found%NC%
        pause
        exit /b 1
    )
)

REM Verify SPECTRA installation
"%VENV_PYTHON%" -c "import tgarchive; print('OK')" >nul 2>&1
if !errorlevel! neq 0 (
    echo %YELLOW%⚠ SPECTRA not properly installed%NC%
    echo %CYAN%→ Running installation repair...%NC%

    if exist "%PROJECT_ROOT%\scripts\spectra_launch.py" (
        "%PYTHON_CMD%" "%PROJECT_ROOT%\scripts\spectra_launch.py" --repair
    ) else (
        echo %RED%✗ Cannot repair installation%NC%
        pause
        exit /b 1
    )
)

echo %GREEN%✓ SPECTRA installation verified%NC%

REM Parse command line arguments
set "MODE=%1"
if "%MODE%"=="" set "MODE=tui"

REM Launch appropriate mode
if "%MODE%"=="tui" goto :launch_tui
if "%MODE%"=="cli" goto :launch_cli
if "%MODE%"=="setup" goto :launch_setup
if "%MODE%"=="check" goto :launch_check
if "%MODE%"=="repair" goto :launch_repair
if "%MODE%"=="--help" goto :show_help
if "%MODE%"=="-h" goto :show_help
if "%MODE%"=="--status" goto :show_status
if "%MODE%"=="--interactive" goto :interactive_mode

echo %RED%Unknown option: %MODE%%NC%
goto :show_help

:launch_tui
echo %CYAN%→ Launching SPECTRA TUI...%NC%

REM Show splash screen if available
if exist "%PROJECT_ROOT%\scripts\spectra_splash.py" (
    "%VENV_PYTHON%" "%PROJECT_ROOT%\scripts\spectra_splash.py" --progress
)

REM Change to project directory and launch
cd /d "%PROJECT_ROOT%"
"%VENV_PYTHON%" -m tgarchive
goto :end

:launch_cli
echo %CYAN%→ SPECTRA CLI Commands:%NC%
"%VENV_PYTHON%" "%PROJECT_ROOT%\scripts\spectra_launch.py" --cli
goto :end

:launch_setup
echo %CYAN%→ Running setup wizard...%NC%
"%VENV_PYTHON%" "%PROJECT_ROOT%\scripts\spectra_launch.py" --setup
goto :end

:launch_check
echo %CYAN%→ Running system check...%NC%
"%VENV_PYTHON%" "%PROJECT_ROOT%\scripts\spectra_launch.py" --check
goto :end

:launch_repair
echo %CYAN%→ Repairing installation...%NC%
"%VENV_PYTHON%" "%PROJECT_ROOT%\scripts\spectra_launch.py" --repair
goto :end

:show_status
echo %CYAN%SPECTRA Quick Status%NC%
echo ====================
echo Platform: Windows

if defined PYTHON_CMD (
    echo %GREEN%✓%NC% Python: %PYTHON_CMD%
) else (
    echo %RED%✗%NC% Python 3.10+ not found
)

if exist "%VENV_PYTHON%" (
    echo %GREEN%✓%NC% Virtual environment: OK
) else (
    echo %YELLOW%⚠%NC% Virtual environment: Missing
)

"%VENV_PYTHON%" -c "import tgarchive; print('OK')" >nul 2>&1
if !errorlevel! equ 0 (
    echo %GREEN%✓%NC% SPECTRA: Installed
) else (
    echo %YELLOW%⚠%NC% SPECTRA: Not installed
)

if exist "%PROJECT_ROOT%\spectra_config.json" (
    echo %GREEN%✓%NC% Configuration: Found
) else (
    echo %YELLOW%⚠%NC% Configuration: Missing
)
goto :end

:interactive_mode
echo %CYAN%SPECTRA Interactive Mode%NC%
echo ========================

call :show_status

echo.
echo What would you like to do?
echo 1. Launch SPECTRA TUI
echo 2. Run setup wizard
echo 3. Show CLI commands
echo 4. Check system status
echo 5. Repair installation
echo 6. Exit

set /p "choice=Enter choice (1-6): "

if "%choice%"=="1" set "MODE=tui" && goto :launch_tui
if "%choice%"=="2" set "MODE=setup" && goto :launch_setup
if "%choice%"=="3" set "MODE=cli" && goto :launch_cli
if "%choice%"=="4" set "MODE=check" && goto :launch_check
if "%choice%"=="5" set "MODE=repair" && goto :launch_repair
if "%choice%"=="6" goto :end
if "%choice%"=="" goto :end

echo %RED%Invalid choice%NC%
goto :end

:show_help
echo %WHITE%SPECTRA Windows Launcher%NC%
echo %CYAN%Usage:%NC% %0 [mode] [options]
echo.
echo %CYAN%Modes:%NC%
echo   %WHITE%tui%NC%      Launch SPECTRA TUI (default)
echo   %WHITE%cli%NC%      Show CLI commands
echo   %WHITE%setup%NC%    Run configuration wizard
echo   %WHITE%check%NC%    Check system status
echo   %WHITE%repair%NC%   Repair installation
echo.
echo %CYAN%Options:%NC%
echo   %WHITE%--help, -h%NC%        Show this help
echo   %WHITE%--status%NC%          Show quick status
echo   %WHITE%--interactive%NC%     Interactive startup mode
echo.
echo %CYAN%Examples:%NC%
echo   %0                     # Launch TUI
echo   %0 setup               # Run setup wizard
echo   %0 cli                 # Show CLI commands
echo   %0 --interactive       # Interactive mode
goto :end

:end
if "%MODE%"=="--interactive" pause
endlocal
