from __future__ import annotations

import os
import time
from typing import Any

from ..models import AgentJob, JobStep
from .openai_common import safe_json_response


REVIEW_MODEL = os.environ.get("AGENT_REVIEW_MODEL", "gpt-5.4-mini")
REVIEW_REASONING_EFFORT = os.environ.get("AGENT_REVIEW_REASONING_EFFORT", "low")


def build_heuristic_review(result_payload: dict[str, Any]) -> dict[str, Any]:
    implementation = result_payload.get("implementation") or {}
    run_result = result_payload.get("run_result") or {}
    test_result = result_payload.get("test_result") or {}
    validation = implementation.get("validation") or {}
    test_failed = int(test_result.get("failed", validation.get("failed", 0)) or 0)

    issues: list[dict[str, str]] = []
    if run_result.get("error"):
        issues.append({"severity": "critical", "title": "실행 실패", "detail": str(run_result.get("error"))[:200]})
    for failure in (test_result.get("failures") or validation.get("failures") or [])[:3]:
        issues.append({"severity": "major", "title": "검증 실패", "detail": str(failure.get("note") or failure)[:200]})
    if not implementation.get("written_files"):
        issues.append({"severity": "major", "title": "결과물 부족", "detail": "작성된 파일이 기록되지 않았습니다."})

    critical = sum(1 for issue in issues if issue["severity"] == "critical")
    major = sum(1 for issue in issues if issue["severity"] == "major")
    minor = sum(1 for issue in issues if issue["severity"] == "minor")

    overall_status = "good"
    if critical > 0:
        overall_status = "blocked"
    elif major > 0 or test_failed > 0:
        overall_status = "needs_work"

    return {
        "summary": "실행과 검증 결과를 바탕으로 자동 리뷰를 생성했습니다.",
        "overall_status": overall_status,
        "severity_counts": {"critical": critical, "major": major, "minor": minor},
        "issues": issues,
        "next_steps": [
            "치명 오류가 있으면 엔트리포인트와 의존성부터 수정합니다." if critical else "핵심 요구사항 반영도를 높입니다.",
            "실패한 검증 항목을 기준으로 재수정합니다." if test_failed else "다음 사용자 피드백을 반영할 수 있게 구조를 유지합니다.",
        ],
    }


def build_review(prompt: str, result_payload: dict[str, Any]) -> dict[str, Any]:
    response = safe_json_response(
        developer_text=(
            "You are a grader/reviewer inside a local AI build agent. "
            "Return JSON only with keys: summary, overall_status, severity_counts, issues, next_steps. "
            "overall_status must be one of good, needs_work, blocked. "
            "severity_counts must contain critical, major, minor. "
            "issues must contain severity, title, detail."
        ),
        user_payload={"prompt": prompt, "result": result_payload},
        model=REVIEW_MODEL,
        reasoning_effort=REVIEW_REASONING_EFFORT,
    )
    if not response:
        return build_heuristic_review(result_payload)
    return response


class ReviewWorker:
    name = "review_worker"

    def can_handle(self, job: AgentJob) -> bool:
        return job.category == "review"

    def process(self, job: AgentJob) -> AgentJob:
        job.assigned_worker = self.name
        job.stage = "review"
        job.status = "running"
        job.steps = [
            JobStep(name="review_scope", status="done", note="리뷰 입력 자료를 확인했습니다."),
            JobStep(name="risk_scan", status="running", note="실행/테스트/구현 결과를 분석하고 있습니다."),
            JobStep(name="review_report", status="pending", note="최종 리뷰 보고서를 작성합니다."),
        ]
        job.summary = "리뷰 작업이 결과물의 품질을 평가하고 있습니다."

        try:
            result_payload = job.metadata.get("review_payload") or job.result or {}
            report = build_review(job.prompt, result_payload)
            counts = report.get("severity_counts") or {}
            critical = int(counts.get("critical", 0) or 0)
            major = int(counts.get("major", 0) or 0)
            minor = int(counts.get("minor", 0) or 0)
            job.result = report
            job.summary = f"리뷰 완료: 치명 {critical} / 주요 {major} / 경미 {minor}"
            job.status = "error" if critical > 0 else "done"
            job.steps[1].status = "error" if critical > 0 else "done"
            job.steps[1].note = "치명 이슈가 발견되었습니다." if critical > 0 else "주요 리스크 분류를 마쳤습니다."
            job.steps[1].updated_at = time.time()
            job.steps[2].status = "done"
            job.steps[2].note = "리뷰 보고서를 저장했습니다."
            job.steps[2].updated_at = time.time()
        except Exception as exc:
            job.status = "error"
            job.summary = f"리뷰 단계에서 오류가 발생했습니다: {exc}"
            job.result = {"error": str(exc)}
            job.steps[1].status = "error"
            job.steps[1].note = str(exc)
            job.steps[1].updated_at = time.time()

        return job
