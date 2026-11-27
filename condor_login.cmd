@echo off
setlocal
cd /d "%~dp0"

where py >nul 2>nul
if %errorlevel%==0 (
    py -3 "condor_login.py" %*
) else (
    python "condor_login.py" %*
)

set "EXIT_CODE=%errorlevel%"
if not "%EXIT_CODE%"=="0" (
    echo.
    echo Condor login failed or exited with an error.
    pause
)
exit /b %EXIT_CODE%
