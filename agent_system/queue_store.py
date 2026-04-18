from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable

from .models import AgentJob
from .paths import ACTIVE_PROJECT_PATH, JOBS_PATH, PROJECTS_DIR, STATE_PATH


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def append_job(job: AgentJob) -> None:
    JOBS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with JOBS_PATH.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(job.to_dict(), ensure_ascii=False) + "\n")


def load_jobs() -> list[AgentJob]:
    if not JOBS_PATH.exists():
        return []
    jobs: list[AgentJob] = []
    for line in JOBS_PATH.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            jobs.append(AgentJob.from_dict(json.loads(line)))
        except json.JSONDecodeError:
            continue
    return jobs


def save_jobs(jobs: Iterable[AgentJob]) -> None:
    payload = "\n".join(json.dumps(job.to_dict(), ensure_ascii=False) for job in jobs)
    JOBS_PATH.write_text(payload + ("\n" if payload else ""), encoding="utf-8")


def upsert_job(job: AgentJob) -> None:
    jobs = load_jobs()
    for index, existing in enumerate(jobs):
        if existing.id == job.id:
            jobs[index] = job
            save_jobs(jobs)
            return
    append_job(job)


def write_state(payload: dict[str, Any]) -> None:
    _write_json(STATE_PATH, payload)


def read_state() -> dict[str, Any]:
    return _read_json(STATE_PATH)


def project_memory_path(project_id: str) -> Path:
    PROJECTS_DIR.mkdir(parents=True, exist_ok=True)
    safe_id = "".join(ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in project_id).strip("_") or "default"
    return PROJECTS_DIR / f"{safe_id}.json"


def read_project_memory(project_id: str) -> dict[str, Any]:
    if not project_id:
        return {}
    return _read_json(project_memory_path(project_id))


def write_project_memory(project_id: str, payload: dict[str, Any]) -> None:
    _write_json(project_memory_path(project_id), payload)


def read_active_project() -> dict[str, Any]:
    return _read_json(ACTIVE_PROJECT_PATH)


def write_active_project(payload: dict[str, Any]) -> None:
    _write_json(ACTIVE_PROJECT_PATH, payload)


def clear_active_project() -> None:
    write_active_project({})


def delete_project_memory(project_id: str) -> bool:
    if not project_id:
        return False
    path = project_memory_path(project_id)
    if not path.exists():
        return False
    path.unlink()
    return True
