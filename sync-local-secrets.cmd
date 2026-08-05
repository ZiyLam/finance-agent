@echo off
setlocal EnableExtensions

rem Purpose: provide a double-clickable, repository-relative entry point for
rem normalizing the local plaintext bundle, synchronizing Kind, and verifying
rem the deployed settings catalog without requiring a manual PowerShell command.
cd /d "%~dp0"

if /i "%~1"=="--check" goto check

powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\sync_local_secrets.ps1"
set "exit_code=%ERRORLEVEL%"
if not "%exit_code%"=="0" (
    echo.
    echo Finance Agent credential synchronization failed. Exit code: %exit_code%
    echo No credential value was intentionally printed. Review the safe error above.
    pause >nul
    exit /b %exit_code%
)
exit /b 0

:check
if not exist "%~dp0scripts\sync_local_secrets.ps1" exit /b 1
if not exist "%~dp0scripts\normalize_local_secret_file.ps1" exit /b 1
if not exist "%~dp0scripts\sync_kind_secrets.sh" exit /b 1
where powershell.exe >nul 2>&1 || exit /b 1
echo sync-local-secrets launcher check passed.
exit /b 0
