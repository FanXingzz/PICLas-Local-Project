@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0Open-PICLas.ps1"
if errorlevel 1 pause
