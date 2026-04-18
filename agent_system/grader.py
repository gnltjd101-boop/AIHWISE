from __future__ import annotations

from typing import Any


def grade_attempt(attempt: dict[str, Any]) -> dict[str, Any]:
    implementation = attempt.get("implementation") or {}
    run_result = attempt.get("run") or {}
    test_result = attempt.get("test") or {}
    review = attempt.get("review") or {}
    research = attempt.get("research") or {}

    validation = implementation.get("validation") or {}
    run_ok = bool(run_result) and not run_result.get("error")
    test_failed = int(test_result.get("failed", validation.get("failed", 0)) or 0)
    counts = review.get("severity_counts") or {}
    critical = int(counts.get("critical", 0) or 0)
    major = int(counts.get("major", 0) or 0)
    minor = int(counts.get("minor", 0) or 0)
    project_checks = test_result.get("project_checks") or []
    project_check_ok = sum(1 for item in project_checks if str(item.get("status") or "") == "ok")
    upgrade_features = [str(item) for item in implementation.get("upgrade_features") or []]
    upgrade_bonus = int(implementation.get("upgrade_bonus", 0) or 0)
    feedback_alignment = review.get("feedback_alignment") or {}
    feedback_count = int(feedback_alignment.get("confirmed_requirements_count", 0) or 0)
    disliked_count = int(feedback_alignment.get("disliked_patterns_count", 0) or 0)
    source_count = int(
        feedback_alignment.get("source_count", 0)
        or len(research.get("source_cards") or [])
        or len(research.get("sources") or [])
        or 0
    )

    score = 0
    if run_ok:
        score += 35
    score += max(0, 30 - (test_failed * 10))
    score += max(0, 20 - (critical * 15) - (major * 5) - minor)
    if implementation.get("output_dir"):
        score += 10
    if implementation.get("written_files"):
        score += 5
    score += min(6, project_check_ok * 2)
    score += min(8, len(upgrade_features) * 2)
    score += min(6, upgrade_bonus)
    feedback_score = min(9, min(6, feedback_count * 2) + min(3, disliked_count))
    source_score = min(5, source_count)
    score += feedback_score
    score += source_score

    status = "good"
    if critical > 0 or not run_ok:
        status = "blocked"
    elif test_failed > 0 or major > 0:
        status = "needs_work"

    return {
        "score": max(0, min(100, score)),
        "status": status,
        "run_ok": run_ok,
        "test_failed": test_failed,
        "critical": critical,
        "major": major,
        "minor": minor,
        "project_check_ok": project_check_ok,
        "upgrade_features": upgrade_features,
        "upgrade_candidate": implementation.get("upgrade_candidate", ""),
        "feedback_score": feedback_score,
        "source_score": source_score,
        "summary": review.get("summary") or attempt.get("summary") or "",
    }


def choose_best_attempt(attempts: list[dict[str, Any]]) -> dict[str, Any]:
    graded_attempts: list[dict[str, Any]] = []
    for index, attempt in enumerate(attempts):
        grade = grade_attempt(attempt)
        graded_attempts.append({"index": index, "attempt": attempt, "grade": grade})
    graded_attempts.sort(
        key=lambda item: (
            item["grade"]["score"],
            item["grade"]["run_ok"],
            item["grade"]["feedback_score"],
            item["grade"]["source_score"],
            item["grade"]["project_check_ok"],
        ),
        reverse=True,
    )
    best = graded_attempts[0] if graded_attempts else {"index": -1, "attempt": {}, "grade": {"score": 0, "status": "blocked"}}
    comparison = []
    for item in graded_attempts:
        comparison.append(
            {
                "attempt_index": item["index"],
                "score": item["grade"]["score"],
                "status": item["grade"]["status"],
                "summary": item["grade"]["summary"],
                "upgrade_candidate": item["grade"].get("upgrade_candidate", ""),
                "feedback_score": item["grade"].get("feedback_score", 0),
                "source_score": item["grade"].get("source_score", 0),
            }
        )
    return {
        "best_attempt_index": best["index"],
        "score": best["grade"]["score"],
        "status": best["grade"]["status"],
        "best_attempt": best["attempt"],
        "attempt_comparison": comparison,
    }
