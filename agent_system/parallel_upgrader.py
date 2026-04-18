from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any


def build_parallel_upgrade_candidates(best_attempt: dict[str, Any], interpretation: dict[str, Any], plan: dict[str, Any]) -> list[dict[str, Any]]:
    implementation = best_attempt.get("implementation") or {}
    app_type = str(implementation.get("app_type") or "")
    output_dir = str(implementation.get("output_dir") or "")
    base_score = 50
    if app_type == "static_web_mvp":
        base_score = 70
    elif app_type == "python_cli_mvp":
        base_score = 64

    candidates = [
        {
            "name": "ui_improvement",
            "goal": "화면 구조와 시각적 계층을 더 분명하게 만든다.",
            "prompt_addition": "현재 결과를 유지하면서 UI 가독성, 카드 구성, 상태 요약, 시각적 완성도를 높여라.",
            "estimated_gain": base_score + 8,
            "write_scope": output_dir,
        },
        {
            "name": "performance_improvement",
            "goal": "기능은 유지하면서 불필요한 로딩과 파일 복잡도를 줄인다.",
            "prompt_addition": "현재 기능을 유지하면서 더 가볍고 단순하게 정리하라. 불필요한 구조와 과한 렌더링은 줄여라.",
            "estimated_gain": base_score + 4,
            "write_scope": output_dir,
        },
        {
            "name": "test_hardening",
            "goal": "자동 검증 범위를 늘려 회귀를 줄인다.",
            "prompt_addition": "현재 결과물에 맞는 스모크 테스트나 검증 스크립트를 추가하고 실행 가능하게 유지하라.",
            "estimated_gain": base_score + 6,
            "write_scope": output_dir,
        },
        {
            "name": "code_cleanup",
            "goal": "파일 역할과 구조를 더 명확하게 정리한다.",
            "prompt_addition": "기능은 유지하면서 파일 역할과 문서를 더 명확히 하고, 유지보수가 쉬운 형태로 정리하라.",
            "estimated_gain": base_score + 3,
            "write_scope": output_dir,
        },
    ]
    for candidate in candidates:
        candidate["domain_mode"] = interpretation.get("domain_mode", "general_mode")
        candidate["current_app_type"] = app_type
    return candidates


def select_recommended_upgrade(candidates: list[dict[str, Any]]) -> dict[str, Any]:
    if not candidates:
        return {}
    ranked = sorted(candidates, key=lambda item: int(item.get("estimated_gain", 0) or 0), reverse=True)
    best = dict(ranked[0])
    best["reason"] = "현재 결과물 기준으로 기대 개선 폭이 가장 큽니다."
    return best


def prepare_upgrade_directory(base_output_dir: str, candidate_name: str) -> Path:
    source_dir = Path(base_output_dir)
    parent = source_dir / "_upgrades"
    target_dir = parent / candidate_name
    parent.mkdir(parents=True, exist_ok=True)
    if target_dir.exists():
        resolved_parent = parent.resolve()
        resolved_target = target_dir.resolve()
        if resolved_parent in resolved_target.parents:
            shutil.rmtree(target_dir)
    if source_dir.exists():
        shutil.copytree(source_dir, target_dir, dirs_exist_ok=True, ignore=shutil.ignore_patterns("_upgrades", "__pycache__"))
    else:
        target_dir.mkdir(parents=True, exist_ok=True)
    return target_dir


def choose_best_parallel_candidate(executed_candidates: list[dict[str, Any]]) -> dict[str, Any]:
    if not executed_candidates:
        return {}
    ranked = sorted(
        executed_candidates,
        key=lambda item: (
            int((item.get("grade") or {}).get("score", 0) or 0),
            bool((item.get("grade") or {}).get("status") == "good"),
        ),
        reverse=True,
    )
    return ranked[0]
