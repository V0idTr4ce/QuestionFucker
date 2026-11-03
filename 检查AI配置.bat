@echo off
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\check-config.ps1"
if errorlevel 1 pause
