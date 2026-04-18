@echo off
setlocal

if "%~1"=="" (
  echo 사용법: launch_orchestrator.bat "여기에 작업 요청"
  exit /b 1
)

pushd "%~dp0.."
python -m agent_system.orchestrator %*
popd

endlocal
