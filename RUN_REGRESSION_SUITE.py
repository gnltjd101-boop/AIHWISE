from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from agent_system.orchestrator import run_once  # noqa: E402


SCENARIOS: list[dict[str, Any]] = [
    {
        "name": "dashboard_basic",
        "prompt": "무의존성 테스트용 대시보드 만들어",
        "expect_browser": True,
        "min_score": 70,
    },
    {
        "name": "automation_basic",
        "prompt": "무의존성 자동화 도구 만들어",
        "expect_browser": True,
        "min_score": 70,
    },
    {
        "name": "docs_informed_build",
        "prompt": "파이썬 http.server 문서 참고해서 무의존성 안내 페이지 만들어",
        "expect_browser": True,
        "min_score": 70,
    },
    {
        "name": "browser_only",
        "prompt": "https://docs.python.org/3/library/http.server.html 열어서 요약해",
        "expect_browser": True,
        "min_score": 50,
    },
]


def safe_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def evaluate_result(scenario: dict[str, Any], state: dict[str, Any]) -> tuple[bool, list[str], dict[str, Any]]:
    issues: list[str] = []
    result = safe_dict(state.get("result"))
    grade = safe_dict(result.get("grade"))
    best_attempt = safe_dict(result.get("best_attempt"))
    implementation = safe_dict(best_attempt.get("implementation"))
    browser = safe_dict(best_attempt.get("browser"))

    status = str(state.get("status") or "")
    score = int(grade.get("score", 0) or 0)
    output_dir = str(implementation.get("output_dir") or "")

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

    summary = {
        "status": status,
        "score": score,
        "projectId": state.get("projectId"),
        "output_dir": output_dir,
        "browser_mode": browser.get("mode", ""),
        "browser_url": browser.get("url", ""),
        "app_type": implementation.get("app_type", ""),
    }
    return len(issues) == 0, issues, summary


def main() -> int:
    os.environ.setdefault("OPENAI_API_KEY", "")
    report: dict[str, Any] = {
        "cwd": str(ROOT),
        "openai_key_present": bool(os.environ.get("OPENAI_API_KEY")),
        "scenarios": [],
    }
    overall_ok = True

    for scenario in SCENARIOS:
        state = run_once(str(scenario["prompt"]))
        ok, issues, summary = evaluate_result(scenario, state)
        report["scenarios"].append(
            {
                "name": scenario["name"],
                "prompt": scenario["prompt"],
                "ok": ok,
                "issues": issues,
                "summary": summary,
            }
        )
        overall_ok = overall_ok and ok

    report["overall_ok"] = overall_ok
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if overall_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
