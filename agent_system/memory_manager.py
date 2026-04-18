from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from .git_tools import summarize_git_status
from .paths import OUTPUT_DIR
from .queue_store import read_active_project, read_project_memory, write_active_project, write_project_memory


def summarize_memory(memory: dict[str, Any]) -> str:
    if not memory:
        return ""
    lines: list[str] = []
    if memory.get("current_goal"):
        lines.append(f"현재 목표: {memory['current_goal']}")
    if memory.get("project_type"):
        lines.append(f"프로젝트 유형: {memory['project_type']}")
    if memory.get("latest_output_dir"):
        lines.append(f"최근 결과물 위치: {memory['latest_output_dir']}")
    git_summary = summarize_git_status(memory.get("git"))
    if git_summary:
        lines.append(f"Git: {git_summary}")
    if memory.get("recent_failure_causes"):
        lines.append("최근 실패 원인:")
        lines.extend(f"- {item}" for item in (memory.get("recent_failure_causes") or [])[:5])
    if memory.get("recent_successful_fixes"):
        lines.append("최근 성공한 수정:")
        lines.extend(f"- {item}" for item in (memory.get("recent_successful_fixes") or [])[:5])
    if memory.get("confirmed_requirements"):
        lines.append("확정 요구사항:")
        lines.extend(f"- {item}" for item in (memory.get("confirmed_requirements") or [])[:6])
    if memory.get("todo"):
        lines.append("남은 TODO:")
        lines.extend(f"- {item}" for item in (memory.get("todo") or [])[:6])
    return "\n".join(lines).strip()


def select_output_dir(project_id: str, memory: dict[str, Any], continuation: bool) -> Path:
    if continuation:
        latest_output_dir = str(memory.get("latest_output_dir") or "").strip()
        if latest_output_dir:
            return Path(latest_output_dir)
    return OUTPUT_DIR / project_id


def build_target_dir_hint(output_dir: Path) -> str:
    return f"TARGET_OUTPUT_DIR: {output_dir}"


def _append_limited(existing: list[str], new_items: list[str], limit: int) -> list[str]:
    merged = list(existing)
    for item in new_items:
        normalized = str(item).strip()
        if normalized and normalized not in merged:
            merged.append(normalized)
    return merged[-limit:]


def update_project_memory(
    project_id: str,
    prompt: str,
    interpretation: dict[str, Any],
    plan: dict[str, Any],
    best_attempt: dict[str, Any],
    grade: dict[str, Any],
    failure_analysis: dict[str, Any] | None = None,
    git_info: dict[str, Any] | None = None,
) -> dict[str, Any]:
    memory = read_project_memory(project_id)
    failure_analysis = failure_analysis or {}
    implementation = best_attempt.get("implementation") or {}
    run_result = best_attempt.get("run") or {}
    review = best_attempt.get("review") or {}

    latest_output_dir = str(implementation.get("output_dir") or memory.get("latest_output_dir") or "")
    recent_failures = _append_limited(
        list(memory.get("recent_failure_causes") or []),
        [str(item) for item in failure_analysis.get("failure_types") or []],
        10,
    )
    recent_successes = _append_limited(
        list(memory.get("recent_successful_fixes") or []),
        [str(item) for item in failure_analysis.get("recommended_fixes") or [] if item],
        10,
    )
    confirmed_requirements = _append_limited(
        list(memory.get("confirmed_requirements") or []),
        [str(item) for item in interpretation.get("confirmed_requirements") or []],
        15,
    )
    next_priorities = _append_limited(
        list(memory.get("next_priorities") or []),
        [str(item) for item in review.get("next_steps") or []] + [str(item) for item in plan.get("next_priorities") or []],
        10,
    )
    todo = _append_limited(
        list(memory.get("todo") or []),
        [str(item) for item in review.get("next_steps") or []],
        12,
    )
    version_history = list(memory.get("version_history") or [])
    version_history.append(
        {
            "timestamp": time.time(),
            "goal": interpretation.get("goal_summary", ""),
            "score": grade.get("score", 0),
            "status": grade.get("status", ""),
            "output_dir": latest_output_dir,
            "git_head": (git_info or {}).get("head", ""),
            "git_branch": (git_info or {}).get("branch", ""),
        }
    )
    version_history = version_history[-12:]

    memory.update(
        {
            "project_id": project_id,
            "title": interpretation.get("project_title") or memory.get("title") or prompt[:80],
            "current_goal": interpretation.get("goal_summary") or prompt,
            "project_type": interpretation.get("domain_mode") or "general_mode",
            "current_stage": grade.get("status") or "completed",
            "latest_output_dir": latest_output_dir,
            "latest_prompt": prompt,
            "latest_summary": review.get("summary") or implementation.get("goal_summary") or "",
            "recent_failure_causes": recent_failures,
            "recent_successful_fixes": recent_successes,
            "disliked_patterns": memory.get("disliked_patterns") or interpretation.get("disliked_patterns") or [],
            "confirmed_requirements": confirmed_requirements,
            "next_priorities": next_priorities,
            "version_history": version_history,
            "todo": todo,
            "last_grade": grade,
            "last_run_result": run_result,
            "last_review_report": review,
            "git": git_info or memory.get("git") or {},
            "updated_at": time.time(),
        }
    )
    write_project_memory(project_id, memory)
    write_active_project(
        {
            "project_id": project_id,
            "title": memory.get("title", ""),
            "latest_output_dir": latest_output_dir,
            "updated_at": memory.get("updated_at"),
        }
    )
    return memory


def apply_user_feedback(command_text: str) -> str:
    active = read_active_project()
    project_id = str(active.get("project_id") or "").strip()
    if not project_id:
        return "활성 프로젝트가 없어 피드백을 저장할 수 없습니다."

    memory = read_project_memory(project_id)
    text = command_text.strip()
    updated = False

    if text.startswith("이 방식 싫어:"):
        value = text.split(":", 1)[1].strip()
        if value:
            memory["disliked_patterns"] = _append_limited(list(memory.get("disliked_patterns") or []), [value], 12)
            updated = True
            message = f"싫어하는 방식으로 기록했습니다: {value}"
        else:
            message = "기록할 내용을 찾지 못했습니다."
    elif text.startswith("이 요구 확정:"):
        value = text.split(":", 1)[1].strip()
        if value:
            memory["confirmed_requirements"] = _append_limited(list(memory.get("confirmed_requirements") or []), [value], 20)
            updated = True
            message = f"확정 요구사항으로 기록했습니다: {value}"
        else:
            message = "기록할 요구사항을 찾지 못했습니다."
    elif text.startswith("다음 우선순위:"):
        value = text.split(":", 1)[1].strip()
        if value:
            memory["next_priorities"] = _append_limited(list(memory.get("next_priorities") or []), [value], 12)
            memory["todo"] = _append_limited(list(memory.get("todo") or []), [value], 12)
            updated = True
            message = f"다음 우선순위로 기록했습니다: {value}"
        else:
            message = "기록할 우선순위를 찾지 못했습니다."
    elif text.startswith("좋았던 점:"):
        value = text.split(":", 1)[1].strip()
        if value:
            memory["recent_successful_fixes"] = _append_limited(list(memory.get("recent_successful_fixes") or []), [value], 12)
            updated = True
            message = f"좋았던 점으로 기록했습니다: {value}"
        else:
            message = "기록할 내용을 찾지 못했습니다."
    else:
        return ""

    if updated:
        memory["updated_at"] = time.time()
        write_project_memory(project_id, memory)
        write_active_project(
            {
                "project_id": project_id,
                "title": memory.get("title", active.get("title", "")),
                "latest_output_dir": memory.get("latest_output_dir", active.get("latest_output_dir", "")),
                "updated_at": memory.get("updated_at"),
            }
        )
    return message
