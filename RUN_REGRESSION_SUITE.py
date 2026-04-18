from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from agent_system.orchestrator import run_once  # noqa: E402


PROFILE_ENV = "AGENT_REGRESSION_PROFILE"
EXTENDED_ENV = "AGENT_REGRESSION_EXTENDED"
DEFAULT_PROFILE = "base"


BASE_SCENARIOS: list[dict[str, Any]] = [
    {
        "name": "automation_basic",
        "prompt": "무의존성 자동화 도구 만들어",
        "expect_browser": True,
        "expect_domain": "automation_mode",
        "expect_route": "coding",
        "min_score": 70,
    },
    {
        "name": "finance_dashboard",
        "prompt": "업비트 빗썸 시세차익 비교용 무의존성 대시보드 만들어",
        "expect_browser": True,
        "expect_domain": "finance_mode",
        "expect_route": "coding",
        "min_score": 65,
    },
    {
        "name": "app_basic",
        "prompt": "무의존성 일정 관리 앱 프로토타입 만들어",
        "expect_browser": True,
        "expect_domain": "app_mode",
        "expect_route": "coding",
        "min_score": 65,
    },
    {
        "name": "data_basic",
        "prompt": "무의존성 크롤링 결과 정리 도구 만들어",
        "expect_browser": True,
        "expect_domain": "data_mode",
        "expect_route": "coding",
        "min_score": 65,
    },
    {
        "name": "browser_only",
        "prompt": "https://docs.python.org/3/library/http.server.html 열어서 요약해",
        "expect_browser": True,
        "expect_route": "browser",
        "min_score": 50,
    },
]

EXTENDED_SCENARIOS: list[dict[str, Any]] = [
    {
        "name": "dashboard_basic",
        "prompt": "무의존성 테스트용 대시보드 만들어",
        "expect_browser": True,
        "expect_domain": "dashboard_mode",
        "expect_route": "coding",
        "min_score": 70,
    },
    {
        "name": "docs_informed_build",
        "prompt": "파이썬 http.server 문서 참고해서 무의존성 안내 페이지 만들어",
        "expect_browser": True,
        "expect_route": "coding",
        "min_score": 70,
    },
]

STRESS_SCENARIOS: list[dict[str, Any]] = [
    {
        "name": "finance_tool",
        "prompt": "무의존성 거래 전략 비교 대시보드와 로그 출력 구조 만들어",
        "expect_browser": True,
        "expect_domain": "finance_mode",
        "expect_route": "coding",
        "min_score": 70,
    },
    {
        "name": "automation_logging",
        "prompt": "무의존성 파일 처리 자동화 도구 만들고 로그 파일도 남기게 해",
        "expect_browser": True,
        "expect_domain": "automation_mode",
        "expect_route": "coding",
        "min_score": 70,
    },
    {
        "name": "app_feedback_ready",
        "prompt": "무의존성 일정 관리 앱 만들고 파일을 나눠서 유지보수 쉽게 구성해",
        "expect_browser": True,
        "expect_domain": "app_mode",
        "expect_route": "coding",
        "min_score": 70,
    },
]


def safe_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def load_profile() -> str:
    explicit = os.environ.get(PROFILE_ENV, "").strip().lower()
    if explicit in {"base", "extended", "stress"}:
        return explicit
    include_extended = os.environ.get(EXTENDED_ENV, "").strip().lower() in {"1", "true", "yes", "on"}
    return "extended" if include_extended else DEFAULT_PROFILE


def load_scenarios() -> tuple[str, list[dict[str, Any]]]:
    profile = load_profile()
    if profile == "stress":
        return profile, [*BASE_SCENARIOS, *EXTENDED_SCENARIOS, *STRESS_SCENARIOS]
    if profile == "extended":
        return profile, [*BASE_SCENARIOS, *EXTENDED_SCENARIOS]
    return profile, list(BASE_SCENARIOS)


def evaluate_result(scenario: dict[str, Any], state: dict[str, Any]) -> tuple[bool, list[str], dict[str, Any]]:
    issues: list[str] = []
    result = safe_dict(state.get("result"))
    grade = safe_dict(result.get("grade"))
    best_attempt = safe_dict(result.get("best_attempt"))
    implementation = safe_dict(best_attempt.get("implementation"))
    browser = safe_dict(best_attempt.get("browser"))
    interpretation = safe_dict(result.get("interpretation"))
    review = safe_dict(best_attempt.get("review"))

    status = str(state.get("status") or "")
    score = int(grade.get("score", 0) or 0)
    output_dir = str(implementation.get("output_dir") or "")
    domain_mode = str(state.get("domainMode") or interpretation.get("domain_mode") or "")
    route_category = str(state.get("category") or interpretation.get("route_category") or "")

    if status not in {"done", "error"}:
        issues.append(f"unexpected status: {status}")
    if status != "done":
        issues.append(f"job did not finish cleanly: {status}")
    if score < int(scenario.get("min_score", 0) or 0):
        issues.append(f"score below threshold: {score}")
    if implementation and output_dir and not Path(output_dir).exists():
        issues.append(f"missing output directory: {output_dir}")
    if scenario.get("expect_browser") and not browser:
        issues.append("missing browser context")
    expected_domain = str(scenario.get("expect_domain") or "")
    if expected_domain and domain_mode != expected_domain:
        issues.append(f"unexpected domain: {domain_mode}")
    expected_route = str(scenario.get("expect_route") or "")
    if expected_route and route_category != expected_route:
        issues.append(f"unexpected route: {route_category}")

    summary = {
        "status": status,
        "score": score,
        "projectId": state.get("projectId"),
        "domain_mode": domain_mode,
        "route_category": route_category,
        "output_dir": output_dir,
        "browser_mode": browser.get("mode", ""),
        "browser_url": browser.get("url", ""),
        "app_type": implementation.get("app_type", ""),
        "review_summary": review.get("summary", ""),
    }
    return len(issues) == 0, issues, summary


def build_aggregate_report(items: list[dict[str, Any]]) -> dict[str, Any]:
    if not items:
        return {
            "scenario_count": 0,
            "passed_count": 0,
            "failed_count": 0,
            "avg_score": 0,
            "avg_elapsed_seconds": 0,
            "max_elapsed_seconds": 0,
        }
    scores = [int((item.get("summary") or {}).get("score", 0) or 0) for item in items]
    elapsed = [float((item.get("summary") or {}).get("elapsed_seconds", 0.0) or 0.0) for item in items]
    passed = sum(1 for item in items if item.get("ok"))
    return {
        "scenario_count": len(items),
        "passed_count": passed,
        "failed_count": len(items) - passed,
        "avg_score": round(sum(scores) / len(scores), 2),
        "avg_elapsed_seconds": round(sum(elapsed) / len(elapsed), 2),
        "max_elapsed_seconds": round(max(elapsed), 2),
    }


def main() -> int:
    os.environ["OPENAI_API_KEY"] = ""
    profile, scenarios = load_scenarios()
    report: dict[str, Any] = {
        "cwd": str(ROOT),
        "openai_key_present": bool(os.environ.get("OPENAI_API_KEY")),
        "profile": profile,
        "scenarios": [],
    }
    overall_ok = True

    for scenario in scenarios:
        started_at = time.time()
        state = run_once(str(scenario["prompt"]))
        ok, issues, summary = evaluate_result(scenario, state)
        summary["elapsed_seconds"] = round(time.time() - started_at, 2)
        item = {
            "name": scenario["name"],
            "prompt": scenario["prompt"],
            "ok": ok,
            "issues": issues,
            "summary": summary,
        }
        report["scenarios"].append(item)
        overall_ok = overall_ok and ok

    report["aggregate"] = build_aggregate_report(report["scenarios"])
    report["overall_ok"] = overall_ok
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if overall_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
