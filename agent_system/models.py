from __future__ import annotations

from dataclasses import asdict, dataclass, field
import time
import uuid
from typing import Any


def new_id() -> str:
    return str(uuid.uuid4())


@dataclass
class JobStep:
    name: str
    status: str = "pending"
    note: str = ""
    updated_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class AgentJob:
    prompt: str
    category: str = "unknown"
    project_id: str = ""
    domain_mode: str = "general_mode"
    stage: str = "queued"
    goal: str = ""
    status: str = "queued"
    id: str = field(default_factory=new_id)
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    assigned_worker: str = ""
    summary: str = ""
    result: Any = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    artifacts: dict[str, Any] = field(default_factory=dict)
    scores: dict[str, Any] = field(default_factory=dict)
    tags: list[str] = field(default_factory=list)
    steps: list[JobStep] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["steps"] = [step.to_dict() for step in self.steps]
        return payload

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "AgentJob":
        job = cls(
            id=str(raw.get("id") or new_id()),
            prompt=str(raw.get("prompt") or ""),
            category=str(raw.get("category") or "unknown"),
            project_id=str(raw.get("project_id") or ""),
            domain_mode=str(raw.get("domain_mode") or "general_mode"),
            stage=str(raw.get("stage") or "queued"),
            goal=str(raw.get("goal") or ""),
            status=str(raw.get("status") or "queued"),
            created_at=float(raw.get("created_at") or time.time()),
            updated_at=float(raw.get("updated_at") or time.time()),
            assigned_worker=str(raw.get("assigned_worker") or ""),
            summary=str(raw.get("summary") or ""),
            result=raw.get("result") if "result" in raw else "",
            metadata=raw.get("metadata") if isinstance(raw.get("metadata"), dict) else {},
            artifacts=raw.get("artifacts") if isinstance(raw.get("artifacts"), dict) else {},
            scores=raw.get("scores") if isinstance(raw.get("scores"), dict) else {},
            tags=[str(item) for item in raw.get("tags") or []],
        )
        job.steps = [
            JobStep(
                name=str(step.get("name") or ""),
                status=str(step.get("status") or "pending"),
                note=str(step.get("note") or ""),
                updated_at=float(step.get("updated_at") or time.time()),
            )
            for step in raw.get("steps") or []
            if isinstance(step, dict)
        ]
        return job
