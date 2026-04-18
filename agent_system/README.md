# Agent System

`agent_system`은 로컬 AI 작업 에이전트의 핵심 실행 엔진입니다.  
채팅 서버에서 받은 요청을 해석하고, 조사/코딩/실행/테스트/리뷰를 거쳐 결과물과 프로젝트 메모리를 저장합니다.

## 현재 구조

```text
agent_system/
  __init__.py
  failure_analyzer.py
  git_tools.py
  grader.py
  interpreter.py
  memory_manager.py
  models.py
  orchestrator.py
  parallel_upgrader.py
  paths.py
  planner.py
  queue_store.py
  launch_orchestrator.bat
  workers/
    __init__.py
    browser_worker.py
    coding_worker.py
    openai_common.py
    research_worker.py
    review_worker.py
    run_worker.py
    test_worker.py
```

## 핵심 역할

- `orchestrator.py`
  - 전체 파이프라인 진입점
  - 요청 해석, 워커 호출, 실패 분석, 병렬 업그레이드, 최종 선택 담당

- `interpreter.py`
  - 사용자의 자연어 요청을 작업 유형과 도메인으로 분류

- `planner.py`
  - 도메인별 우선순위와 실행 계획 생성

- `memory_manager.py`
  - 프로젝트 메모리 저장
  - 현재 목표, 실패 원인, TODO, 버전 히스토리 관리

- `failure_analyzer.py`
  - 실패 유형 분류
  - 재시도용 수정 방향 생성

- `grader.py`
  - 시도별 점수 계산
  - base 결과와 업그레이드 후보 중 최종 결과 선택

- `parallel_upgrader.py`
  - UI 개선, 테스트 강화 같은 후보 업그레이드 분기 실행 지원

- `git_tools.py`
  - 로컬 Git 저장소 상태 확인
  - 브랜치, 커밋, dirty 상태를 프로젝트 메모리에 반영

## 워커 역할

- `research_worker.py`
  - 조사 보고서 생성

- `coding_worker.py`
  - 결과물 생성 및 수정
  - 무의존성 폴백 MVP 생성

- `run_worker.py`
  - 정적 웹, Python CLI, Python 웹, Node 앱 실행 검증

- `test_worker.py`
  - 문법 검사
  - 스모크 테스트
  - 결과물 구조 검증

- `review_worker.py`
  - 구현 결과에 대한 자동 리뷰 생성

- `browser_worker.py`
  - 브라우저 검색/탐색 계열 작업 담당

## 데이터 저장 위치

- 작업 로그: `agent_jobs.jsonl`
- 최신 작업 상태: `agent_job_state.json`
- 활성 프로젝트: `agent_active_project.json`
- 프로젝트 메모리: `agent_projects/`
- 결과물: `agent_outputs/`

## 현재 동작 흐름

1. 채팅 서버가 요청을 받음
2. 오케스트레이터가 요청을 해석
3. 조사 -> 코딩 -> 실행 -> 테스트 -> 리뷰 진행
4. 실패 시 실패 분석 후 재시도
5. 병렬 업그레이드 후보 실행
6. 점수 기반으로 최종 결과 선택
7. 결과물, 상태, 프로젝트 메모리 저장

## 유지보수 원칙

- 기존 구조를 버리지 않고 오케스트레이터 중심으로 확장
- 무거운 외부 의존성보다 무의존성 MVP 우선
- 결과물은 반드시 실행 또는 검증 가능해야 함
- 프로젝트 메모리는 다음 고도화에 바로 이어질 수 있어야 함
