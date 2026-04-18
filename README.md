# AIHWISE

로컬에서 실행되는 지속 개선형 AI 작업 에이전트입니다.  
사용자가 채팅창에 아이디어를 입력하면 요청을 해석하고, 필요한 경우 조사하고, 코드를 만들거나 수정하고, 실행/테스트/리뷰까지 거쳐 결과물을 저장합니다.

## 현재 가능한 것

- 자연어 요청을 프로젝트 성격별로 분류
- 조사 -> 코딩 -> 실행 -> 테스트 -> 리뷰 자동 루프
- 실패 시 원인 분석 후 재시도
- 프로젝트 메모리 저장 및 이어서 고도화
- 결과물 병렬 업그레이드 후보 실행 후 더 나은 결과 선택
- 로컬 Git 상태 기록

## 대표 요청 예시

- `업비트/빗썸 시세차익 대시보드 만들어`
- `무의존성 자동화 도구 만들어`
- `현재 프로젝트 고도화해`
- `현재 프로젝트 확인`
- `이 요구 확정: 로그 파일 남기기`
- `다음 우선순위: 테스트 더 강화`

## 폴더 구조

```text
AI에이전트/
  README.md
  agent_chat_server.py
  OPEN_AGENT_CHAT.bat
  agent_jobs.jsonl
  agent_job_state.json
  agent_chat_history.jsonl
  agent_chat_meta.json
  agent_active_project.json
  agent_outputs/
  agent_projects/
  agent_system/
```

## 주요 파일

- `agent_chat_server.py`
  - 로컬 채팅 UI와 API 서버

- `OPEN_AGENT_CHAT.bat`
  - 채팅 서버 실행용 배치 파일

- `agent_system/orchestrator.py`
  - 전체 작업 파이프라인 중심 엔진

- `agent_system/workers/*.py`
  - 조사, 코딩, 실행, 테스트, 리뷰 워커

## 빠른 실행

PowerShell 기준:

```powershell
cd "C:\Users\휘새\Desktop\AI에이전트"
python -m py_compile .\agent_chat_server.py
.\OPEN_AGENT_CHAT.bat
```

브라우저가 열리면 채팅창에서 요청을 바로 입력하면 됩니다.

## 무의존성 검증 실행

OpenAI 키 없이도 폴백 경로를 검증할 수 있습니다.

```powershell
cd "C:\Users\휘새\Desktop\AI에이전트"
$env:OPENAI_API_KEY=""
python -c "import sys,json; sys.path.insert(0, r'C:\Users\휘새\Desktop\AI에이전트'); from agent_system.orchestrator import run_once; print(json.dumps(run_once('무의존성 테스트용 대시보드 만들어'), ensure_ascii=False, indent=2))"
```

## 회귀 테스트 실행

여러 대표 시나리오를 한 번에 검증하려면:

```powershell
cd "C:\Users\휘새\Desktop\AI에이전트"
.\RUN_REGRESSION_SUITE.bat
```

또는:

```powershell
cd "C:\Users\휘새\Desktop\AI에이전트"
python .\RUN_REGRESSION_SUITE.py
```

성공하면 마지막 JSON의 `overall_ok`가 `true`로 나옵니다.
기본 모드는 빠른 핵심 5개 시나리오만 검사합니다.

확장 모드까지 돌리려면:

```powershell
cd "C:\Users\휘새\Desktop\AI에이전트"
$env:AGENT_REGRESSION_EXTENDED="1"
python .\RUN_REGRESSION_SUITE.py
```

## 브라우저 자동화

기본적으로 일반 로컬 실행 환경에서는 Playwright 브라우저 자동화가 켜집니다.  
제한된 환경에서는 자동으로 폴백 검색 모드로 내려갑니다.

강제로 켜려면:

```powershell
$env:AGENT_ENABLE_PLAYWRIGHT="1"
```

강제로 끄려면:

```powershell
$env:AGENT_ENABLE_PLAYWRIGHT="0"
```

## 프로젝트 명령

채팅창에서 아래 명령을 그대로 쓸 수 있습니다.

- `현재 프로젝트 확인`
- `새 프로젝트로 시작`
- `현재 프로젝트 초기화`
- `이 방식 싫어: ...`
- `이 요구 확정: ...`
- `다음 우선순위: ...`
- `좋았던 점: ...`

## 결과 저장 위치

- 결과물 폴더: `agent_outputs/`
- 프로젝트 메모리: `agent_projects/`
- 최신 상태: `agent_job_state.json`
- 누적 작업 로그: `agent_jobs.jsonl`

## Git 사용

현재 이 프로젝트는 로컬 Git 저장소로 초기화되어 있고 `main` 브랜치를 사용합니다.

기본 작업 흐름:

```powershell
cd "C:\Users\휘새\Desktop\AI에이전트"
git status
git add .
git commit -m "작업 내용"
git push
```

빠르게 한 번에 처리하려면:

```powershell
cd "C:\Users\휘새\Desktop\AI에이전트"
.\AUTO_GIT_SYNC.bat
```

커밋 메시지를 바로 넘기려면:

```powershell
cd "C:\Users\휘새\Desktop\AI에이전트"
.\AUTO_GIT_SYNC.bat "작업 내용"
```

## 현재 설계 방향

- 기존 구조를 살린 오케스트레이터 중심 확장
- 무의존성 MVP 우선
- 실패 복구와 재시도 가능성 확보
- 프로젝트 메모리를 기반으로 반복 고도화
- 결과물 비교와 선택이 가능한 병렬 업그레이드 구조

## 다음 추천 작업

- 브라우저 워커 실전 검색 강화
- 더 많은 실전 요청 회귀 테스트
- 자동 커밋/푸시 보조 스크립트 추가
- 배포용 실행 문서와 예제 프로젝트 추가
