@echo off
setlocal
chcp 65001 >nul

start "Agent Chat Server" cmd /k "python \"%~dp0agent_chat_server.py\""
timeout /t 2 >nul
start "" "http://127.0.0.1:8780"

endlocal
