@echo off
setlocal
cd /d "%~dp0Bin" || exit /b 1
start "" "%~dp0Bin\BrotherDiagnostics.exe"
