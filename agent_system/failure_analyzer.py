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

    project_checks = test_result.get("project_checks") or []
    if any("feedback requirement" in str(item.get("name") or "") and str(item.get("status") or "") != "ok" for item in project_checks):
        failure_types.append("feedback_requirement_missed")
    if any("feedback dislike" in str(item.get("name") or "") and str(item.get("status") or "") != "ok" for item in project_checks):
        failure_types.append("disliked_pattern_regression")
    if any("structure rule" in str(item.get("name") or "") and str(item.get("status") or "") != "ok" for item in project_checks):
        failure_types.append("structure_rule_violation")

    counts = review.get("severity_counts") or {}
    if int(counts.get("critical", 0) or 0) > 0:
        failure_types.append("critical_review_issue")
    if int(counts.get("major", 0) or 0) > 0:
        failure_types.append("major_review_issue")

    source_cards = implementation.get("research_source_summary") or []
    if source_cards and all("[score -" in str(item) or "[score 0]" in str(item) for item in source_cards[:2]):
        failure_types.append("low_source_confidence")

    deduped: list[str] = []
    for item in failure_types:
        if item not in deduped:
            deduped.append(item)
    return deduped


def _build_recommended_fixes(prompt: str, implementation: dict[str, Any], run_result: dict[str, Any], test_result: dict[str, Any], review: dict[str, Any], failure_types: list[str]) -> list[str]:
    fixes: list[str] = []
    if run_result.get("error"):
        fixes.append("엔트리포인트와 실행 명령을 다시 맞춥니다.")
    for failure in test_result.get("failures") or []:
        note = str(failure.get("note") or "").lower()
        if "syntax" in note or "invalid syntax" in note:
            fixes.append("문법 오류가 난 파일을 먼저 수정합니다.")
        if "module" in note or "import" in note:
            fixes.append("누락된 import 또는 파일 경로를 정리합니다.")
    if "feedback_requirement_missed" in failure_types:
        fixes.append("확정 요구사항이 실제 파일과 UI에 보이도록 다시 반영합니다.")
    if "disliked_pattern_regression" in failure_types:
        fixes.append("사용자가 싫어한 방식을 피하도록 구조를 다시 나눕니다.")
    if "structure_rule_violation" in failure_types:
        fixes.append("파일명과 폴더 구조를 규칙에 맞게 다시 정리합니다.")
    if "low_source_confidence" in failure_types:
        fixes.append("공식 문서나 더 신뢰도 높은 출처를 우선 참고하도록 조사 대상을 바꿉니다.")
    for issue in review.get("issues") or []:
        detail = str(issue.get("detail") or "").strip()
        title = str(issue.get("title") or "").strip()
        if title or detail:
            fixes.append(f"{title} {detail}".strip())
    if not fixes:
        fixes.append(f"'{prompt[:40]}' 요청 기준으로 실행 경로와 검증 실패를 우선 수정합니다.")
    deduped: list[str] = []
    for item in fixes:
        if item and item not in deduped:
            deduped.append(item)
    return deduped[:8]


def _build_search_queries(prompt: str, interpretation: dict[str, Any], implementation: dict[str, Any], run_result: dict[str, Any], test_result: dict[str, Any], failure_types: list[str]) -> list[str]:
    goal = str(interpretation.get("goal_summary") or prompt)
    queries = list(interpretation.get("search_queries") or [])
    validation = implementation.get("validation") or {}

    for failure in validation.get("failures") or []:
        note = str(failure.get("note") or "").strip()
        if note:
            queries.append(f"{goal} {note}")
    if run_result.get("error"):
        queries.append(f"{goal} {run_result.get('error')}")
    if "structure_rule_violation" in failure_types:
        queries.append(f"{goal} file structure naming best practice")
    if "feedback_requirement_missed" in failure_types:
        queries.append(f"{goal} implementation checklist requirements mapping")
    if "low_source_confidence" in failure_types:
        queries.append(f"{goal} official documentation")

    deduped: list[str] = []
    for item in queries:
        text = str(item).strip()
        if text and text not in deduped:
            deduped.append(text)
    return deduped[:8]


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
    recommended_fixes = _build_recommended_fixes(prompt, implementation, run_result, test_result, review, failure_types)
    search_queries = _build_search_queries(prompt, interpretation, implementation, run_result, test_result, failure_types)

    counts = review.get("severity_counts") or {}
    blocker = any(
        item in failure_types
        for item in (
            "critical_review_issue",
            "run_failed",
            "tests_failed",
            "structure_rule_violation",
            "feedback_requirement_missed",
        )
    )
    should_retry = bool(failure_types) and attempt_index + 1 < max_attempts

    return {
        "failure_types": failure_types,
        "blocker": blocker,
        "should_retry": should_retry,
        "attempt_index": attempt_index,
        "max_attempts": max_attempts,
        "hypotheses": recommended_fixes[:4],
        "search_queries": search_queries,
        "recommended_fixes": recommended_fixes,
        "review_critical_count": int(counts.get("critical", 0) or 0),
        "review_major_count": int(counts.get("major", 0) or 0),
    }
