# Agent System v1

이 폴더는 기존 단일 에이전트 구조를 `채팅 + 오케스트레이터 + 워커` 구조로 나누기 위한 첫 골격입니다.

## 구조

```text
agent_system/
  README.md
  models.py
  queue_store.py
  orchestrator.py
  launch_orchestrator.bat
  workers/
    __init__.py
    research_worker.py
    coding_worker.py
    test_worker.py
    review_worker.py
```

## 역할

- `orchestrator.py`
  - 사용자 요청을 작업으로 등록
  - 작업 종류를 분류
  - 적절한 워커에 배정
  - 상태를 기록

- `queue_store.py`
  - 작업 큐 파일 저장/조회
  - 상태 파일 저장/조회

- `models.py`
  - 작업, 단계, 상태 모델 정의

- `workers/*.py`
  - 조사, 코딩, 테스트, 리뷰 담당

## 저장 파일

기본 저장 위치:

- `%USERPROFILE%\\agent_jobs.jsonl`
- `%USERPROFILE%\\agent_job_state.json`

## 현재 범위

이 버전은 “상용 수준 자동 작업자”의 완성본이 아니라, 다음 단계 구현을 위한 실행 골격입니다.

현재 가능한 것:

- 작업 등록
- 작업 분류
- 작업 상태 저장
- 워커 디스패치 골격

아직 없는 것:

- 실제 OpenAI 플래닝 통합
- 실제 코드 수정 루프
- 실제 테스트 자동 복구
- 실제 computer use 연계

## 다음 단계

1. 채팅 UI에서 사용자 요청을 `orchestrator.py`로 넣기
2. 각 워커에 실제 OpenAI/로컬 실행 로직 연결
3. 작업 상태를 채팅 UI에서 읽어 진행상황 표시
