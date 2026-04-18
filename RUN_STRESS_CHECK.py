from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent
OUTPUT_DIR = ROOT / "agent_outputs"
REGRESSION_DIR = OUTPUT_DIR / "regression_reports"
DIAGNOSTICS_DIR = OUTPUT_DIR / "diagnostics"
STRESS_DIR = OUTPUT_DIR / "stress_reports"


def latest_file(path: Path, pattern: str) -> Path | None:
    files = sorted(path.glob(pattern), key=lambda item: item.stat().st_mtime) if path.exists() else []
    return files[-1] if files else None


def read_json(path: Path | None) -> dict[str, Any]:
    if path is None or not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def run_python(script_name: str, extra_env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env.setdefault("PYTHONIOENCODING", "utf-8")
    if extra_env:
        env.update(extra_env)
    return subprocess.run(
        ["python", str(ROOT / script_name)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
        cwd=ROOT,
        check=False,
    )


def classify_health(regression: dict[str, Any]) -> tuple[str, list[str]]:
    aggregate = regression.get("aggregate") or {}
    warnings: list[str] = []
    passed_count = int(aggregate.get("passed_count", 0) or 0)
    failed_count = int(aggregate.get("failed_count", 0) or 0)
    avg_score = float(aggregate.get("avg_score", 0) or 0)
    avg_elapsed = float(aggregate.get("avg_elapsed_seconds", 0) or 0)
    max_elapsed = float(aggregate.get("max_elapsed_seconds", 0) or 0)

    if failed_count > 0:
        warnings.append(f"failed scenarios detected: {failed_count}")
    if avg_score < 80:
        warnings.append(f"average score below target: {avg_score}")
    if avg_elapsed > 45:
        warnings.append(f"average elapsed too high: {avg_elapsed}s")
    if max_elapsed > 90:
        warnings.append(f"max elapsed too high: {max_elapsed}s")
    if passed_count == 0:
        warnings.append("no scenarios passed")

    if failed_count > 0:
        return "fail", warnings
    if warnings:
        return "warn", warnings
    return "ok", warnings


def render_markdown(report: dict[str, Any]) -> str:
    regression = report["regression"]
    diagnostics = report["diagnostics"]
    lines = [
        "# Stress Check",
        "",
        f"- created_at: {report['created_at']}",
        f"- health: {report['health']}",
        f"- elapsed_seconds: {report['elapsed_seconds']}",
        "",
        "## Regression",
        "",
        f"- profile: {regression.get('profile', '')}",
        f"- overall_ok: {regression.get('overall_ok', '')}",
        f"- aggregate: {json.dumps(regression.get('aggregate', {}), ensure_ascii=False)}",
        f"- report_path: {report['regression_report_path']}",
        "",
        "## Diagnostics",
        "",
        f"- diagnostics_path: {report['diagnostics_report_path']}",
        f"- latest_output_dir: {(diagnostics.get('artifacts') or {}).get('latest_output_dir', '')}",
        "",
        "## Warnings",
        "",
    ]
    if report["warnings"]:
        lines.extend(f"- {item}" for item in report["warnings"])
    else:
        lines.append("- none")
    return "\n".join(lines) + "\n"


def main() -> int:
    started_at = time.time()
    STRESS_DIR.mkdir(parents=True, exist_ok=True)

    regression_run = run_python("RUN_REGRESSION_SUITE.py", {"AGENT_REGRESSION_PROFILE": "stress"})
    diagnostics_run = run_python("GENERATE_DIAGNOSTICS_REPORT.py")

    latest_regression_path = latest_file(REGRESSION_DIR, "regression_stress_*.json")
    latest_diagnostics_path = latest_file(DIAGNOSTICS_DIR, "diagnostics_*.json")

    regression = read_json(latest_regression_path)
    diagnostics = read_json(latest_diagnostics_path)
    health, warnings = classify_health(regression)

    report = {
        "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "elapsed_seconds": round(time.time() - started_at, 2),
        "health": health,
        "warnings": warnings,
        "regression_exit_code": regression_run.returncode,
        "diagnostics_exit_code": diagnostics_run.returncode,
        "regression_stdout_tail": (regression_run.stdout or "")[-1200:],
        "regression_stderr_tail": (regression_run.stderr or "")[-1200:],
        "diagnostics_stdout_tail": (diagnostics_run.stdout or "")[-1200:],
        "diagnostics_stderr_tail": (diagnostics_run.stderr or "")[-1200:],
        "regression_report_path": str(latest_regression_path) if latest_regression_path else "",
        "diagnostics_report_path": str(latest_diagnostics_path) if latest_diagnostics_path else "",
        "regression": {
            "profile": regression.get("profile", ""),
            "overall_ok": regression.get("overall_ok", False),
            "aggregate": regression.get("aggregate", {}),
        },
        "diagnostics": {
            "git": diagnostics.get("git", {}),
            "latest_state": diagnostics.get("latest_state", {}),
            "artifacts": diagnostics.get("artifacts", {}),
        },
    }

    timestamp = time.strftime("%Y%m%d_%H%M%S")
    json_path = STRESS_DIR / f"stress_check_{timestamp}.json"
    md_path = STRESS_DIR / f"stress_check_{timestamp}.md"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(render_markdown(report), encoding="utf-8")
    print(
        json.dumps(
            {
                "ok": True,
                "health": health,
                "warnings": warnings,
                "json_path": str(json_path),
                "markdown_path": str(md_path),
                "regression_report_path": report["regression_report_path"],
                "diagnostics_report_path": report["diagnostics_report_path"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if health != "fail" else 1


if __name__ == "__main__":
    raise SystemExit(main())
