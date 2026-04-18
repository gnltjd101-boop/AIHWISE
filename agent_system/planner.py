from __future__ import annotations

from typing import Any

from .interpreter import DOMAIN_PRIORITIES


def build_execution_plan(interpretation: dict[str, Any], memory: dict[str, Any] | None = None) -> dict[str, Any]:
    memory = memory or {}
    domain_mode = str(interpretation.get("domain_mode") or "general_mode")
    route_category = str(interpretation.get("route_category") or "coding")
    continuation = bool(interpretation.get("continuation"))
    focus = DOMAIN_PRIORITIES.get(domain_mode, DOMAIN_PRIORITIES["general_mode"])

    pipeline_roles: list[str] = ["task_interpreter", "planner"]
    if interpretation.get("requires_browser"):
        pipeline_roles.append("browser")
    if interpretation.get("requires_research"):
        pipeline_roles.append("researcher")
    if interpretation.get("requires_build"):
        pipeline_roles.append("builder")
    if interpretation.get("requires_run"):
        pipeline_roles.append("runner")
    if interpretation.get("requires_test"):
        pipeline_roles.append("tester")
    if interpretation.get("requires_review"):
        pipeline_roles.extend(["failure_analyzer", "grader", "memory_manager"])

    next_priorities = list(dict.fromkeys([*focus, *(memory.get("next_priorities") or [])]))[:6]

    return {
        "route_category": route_category,
        "domain_mode": domain_mode,
        "pipeline_roles": pipeline_roles,
        "research_focus": focus,
        "builder_scope": interpretation.get("mvp_scope") or focus[:3],
        "test_focus": [
            "문법 및 파일 유효성",
            "프로젝트 엔트리포인트 실행",
            "핵심 사용자 흐름 최소 검증",
        ],
        "review_focus": [
            "실행 성공 여부",
            "테스트 실패 여부",
            "핵심 요구사항 반영 여부",
            "다음 개선 우선순위",
        ],
        "repair_budget": 2 if route_category == "coding" else 0,
        "continuation_mode": continuation,
        "output_strategy": "continue_existing" if continuation and memory.get("latest_output_dir") else "new_or_existing",
        "parallel_upgrade_candidates": [
            "ui_improvement",
            "performance_improvement",
            "test_hardening",
            "code_cleanup",
        ] if route_category == "coding" else [],
        "next_priorities": next_priorities,
    }
