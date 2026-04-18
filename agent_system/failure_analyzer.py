from __future__ import annotations

from typing import Any


def _collect_failure_types(implementation: dict[str, Any], run_result: dict[str, Any], test_result: dict[str, Any], review: dict[str, Any]) -> list[str]:
    failure_types: list[str] = []
    validation = implementation.get("validation") or {}
    if int(validation.get("failed", 0) or 0) > 0:
        failure_types.append("build_validation_failed")
    if run_result.get("status") == "error" or run_result.get("error"):
        failure_types.append("run_failed")
    if int(test_result.get("failed", 0) or 0) > 0:
        failure_types.append("tests_failed")
    counts = review.get("severity_counts") or {}
    if int(counts.get("critical", 0) or 0) > 0:
        failure_types.append("critical_review_issue")
    if int(counts.get("major", 0) or 0) > 0:
        failure_types.append("major_review_issue")
    return failure_types


def _build_recommended_fixes(run_result: dict[str, Any], test_result: dict[str, Any], review: dict[str, Any]) -> list[str]:
    fixes: list[str] = []
    if run_result.get("error"):
        fixes.append("엔트리포인트와 실행 명령을 다시 맞춘다.")
    for failure in test_result.get("failures") or []:
        note = str(failure.get("note") or "").lower()
        if "syntax" in note or "invalid syntax" in note:
            fixes.append("문법 오류가 난 파일을 먼저 수정한다.")
        if "module" in note or "import" in note:
            fixes.append("누락된 import 또는 파일 경로를 정리한다.")
    for issue in review.get("issues") or []:
        detail = str(issue.get("detail") or "").strip()
        title = str(issue.get("title") or "").strip()
        if title or detail:
            fixes.append(f"{title} {detail}".strip())
    if not fixes:
        fixes.append("실패 로그를 기준으로 핵심 엔트리포인트와 검증 실패를 우선 수정한다.")
    return fixes[:6]


def analyze_failure(
    prompt: str,
    interpretation: dict[str, Any],
    implementation: dict[str, Any],
    run_result: dict[str, Any],
    test_result: dict[str, Any],
    review: dict[str, Any],
    attempt_index: int,
    max_attempts: int,
) -> dict[str, Any]:
    failure_types = _collect_failure_types(implementation, run_result, test_result, review)
    recommended_fixes = _build_recommended_fixes(run_result, test_result, review)
    search_queries = list(interpretation.get("search_queries") or [])

    validation = implementation.get("validation") or {}
    for failure in validation.get("failures") or []:
        note = str(failure.get("note") or "").strip()
        if note:
            search_queries.append(f"{interpretation.get('goal_summary', prompt)} {note}")
    if run_result.get("error"):
        search_queries.append(f"{interpretation.get('goal_summary', prompt)} {run_result.get('error')}")

    counts = review.get("severity_counts") or {}
    should_retry = bool(failure_types) and attempt_index + 1 < max_attempts
    blocker = "critical_review_issue" in failure_types or "run_failed" in failure_types or "tests_failed" in failure_types

    return {
        "failure_types": failure_types,
        "blocker": blocker,
        "should_retry": should_retry,
        "attempt_index": attempt_index,
        "max_attempts": max_attempts,
        "hypotheses": recommended_fixes[:4],
        "search_queries": search_queries[:6],
        "recommended_fixes": recommended_fixes,
        "review_critical_count": int(counts.get("critical", 0) or 0),
        "review_major_count": int(counts.get("major", 0) or 0),
    }
