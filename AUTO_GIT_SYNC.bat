@echo off
setlocal

powershell -ExecutionPolicy Bypass -File "%~dp0AUTO_GIT_SYNC.ps1" %*

endlocal
