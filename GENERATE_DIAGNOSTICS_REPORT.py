from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path
from typing import Any

from agent_system.paths import (
    ACTIVE_PROJECT_PATH,
    HISTORY_PATH,
    JOBS_PATH,
    OUTPUT_DIR,
    PROJECTS_DIR,
    ROOT_DIR,
    STATE_PATH,
)


DIAGNOSTICS_DIR = OUTPUT_DIR / "diagnostics"
REGRESSION_REPORTS_DIR = OUTPUT_DIR / "regression_reports"
BACKUPS_DIR = ROOT_DIR / "agent_backups"


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return {"_error": f"{path.name}: {exc}"}


def count_jsonl_lines(path: Path) -> int:
    if not path.exists():
        return 0
    with path.open("r", encoding="utf-8") as handle:
        return sum(1 for _ in handle if _.strip())


def run_git(*args: str) -> str:
    try:
        completed = subprocess.run(
            ["git", "-C", str(ROOT_DIR), *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        output = (completed.stdout or completed.stderr or "").strip()
        return output
    except Exception as exc:
        return f"git_error: {exc}"


def latest_file(path: Path, pattern: str) -> str:
    files = sorted(path.glob(pattern), key=lambda item: item.stat().st_mtime) if path.exists() else []
    return str(files[-1]) if files else ""


def summarize_state(state: dict[str, Any]) -> dict[str, Any]:
    result = state.get("result") or {}
    grade = result.get("grade") or {}
    review = result.get("review") or {}
    return {
        "status": state.get("status", ""),
        "project_id": state.get("projectId", ""),
        "domain_mode": state.get("domainMode", ""),
        "category": state.get("category", ""),
        "updated_at": state.get("updated_at", ""),
        "score": grade.get("score", ""),
        "rating": grade.get("rating", ""),
        "selected_upgrade": result.get("selected_upgrade") or result.get("best_attempt_label", ""),
        "latest_output_dir": result.get("output_dir", ""),
        "review_summary": review.get("summary", "") or result.get("review_summary", ""),
        "pipeline": state.get("pipeline", []),
    }


def build_report() -> dict[str, Any]:
    state = read_json(STATE_PATH)
    active_project = read_json(ACTIVE_PROJECT_PATH)
    latest_project_memory = read_json(PROJECTS_DIR / f"{active_project.get('project_id', '')}.json") if active_project.get("project_id") else {}
    latest_regression_path = latest_file(REGRESSION_REPORTS_DIR, "regression_*.json")
    latest_regression = read_json(Path(latest_regression_path)) if latest_regression_path else {}

    report = {
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "root_dir": str(ROOT_DIR),
        "git": {
            "branch_status": run_git("status", "--short", "--branch"),
            "head": run_git("rev-parse", "--short", "HEAD"),
            "recent_commit": run_git("log", "-1", "--oneline"),
            "remote": run_git("remote", "-v"),
        },
        "counts": {
            "job_log_entries": count_jsonl_lines(JOBS_PATH),
            "chat_history_entries": count_jsonl_lines(HISTORY_PATH),
            "project_memory_files": len(list(PROJECTS_DIR.glob("*.json"))) if PROJECTS_DIR.exists() else 0,
            "backup_archives": len(list(BACKUPS_DIR.glob("*.zip"))) if BACKUPS_DIR.exists() else 0,
            "regression_reports": len(list(REGRESSION_REPORTS_DIR.glob("*.json"))) if REGRESSION_REPORTS_DIR.exists() else 0,
        },
        "latest_state": summarize_state(state),
        "active_project": active_project,
        "project_memory": {
            "current_goal": latest_project_memory.get("current_goal", ""),
            "project_type": latest_project_memory.get("project_type", ""),
            "current_stage": latest_project_memory.get("current_stage", ""),
            "recent_failure_causes": latest_project_memory.get("recent_failure_causes", []),
            "recent_successful_fixes": latest_project_memory.get("recent_successful_fixes", []),
            "confirmed_requirements": latest_project_memory.get("confirmed_requirements", []),
            "disliked_patterns": latest_project_memory.get("disliked_patterns", []),
            "next_priorities": latest_project_memory.get("next_priorities", []),
            "todo": latest_project_memory.get("todo", []),
            "version_history_count": len(latest_project_memory.get("version_history", [])),
        },
        "latest_regression": {
            "path": latest_regression_path,
            "profile": latest_regression.get("profile", ""),
            "overall_ok": latest_regression.get("overall_ok", ""),
            "aggregate": latest_regression.get("aggregate", {}),
            "created_at": latest_regression.get("created_at", ""),
        },
        "artifacts": {
            "latest_backup": latest_file(BACKUPS_DIR, "*.zip"),
            "latest_regression_report": latest_regression_path,
            "latest_output_dir": summarize_state(state).get("latest_output_dir", ""),
        },
    }
    return report


def render_markdown(report: dict[str, Any]) -> str:
    git = report["git"]
    counts = report["counts"]
    latest_state = report["latest_state"]
    memory = report["project_memory"]
    regression = report["latest_regression"]
    artifacts = report["artifacts"]

    lines = [
        "# AI Agent Diagnostics",
        "",
        f"- generated_at: {report['generated_at']}",
        f"- root_dir: {report['root_dir']}",
        "",
        "## Git",
        "",
        "```text",
        git["branch_status"],
        git["recent_commit"],
        git["remote"],
        "```",
        "",
        "## Counts",
        "",
        f"- jobs: {counts['job_log_entries']}",
        f"- chat_history: {counts['chat_history_entries']}",
        f"- projects: {counts['project_memory_files']}",
        f"- backups: {counts['backup_archives']}",
        f"- regression_reports: {counts['regression_reports']}",
        "",
        "## Latest State",
        "",
        f"- status: {latest_state['status']}",
        f"- project_id: {latest_state['project_id']}",
        f"- domain_mode: {latest_state['domain_mode']}",
        f"- category: {latest_state['category']}",
        f"- score: {latest_state['score']}",
        f"- rating: {latest_state['rating']}",
        f"- selected_upgrade: {latest_state['selected_upgrade']}",
        f"- output_dir: {latest_state['latest_output_dir']}",
        f"- review_summary: {latest_state['review_summary']}",
        "",
        "## Project Memory",
        "",
        f"- current_goal: {memory['current_goal']}",
        f"- project_type: {memory['project_type']}",
        f"- current_stage: {memory['current_stage']}",
        f"- confirmed_requirements: {', '.join(memory['confirmed_requirements']) if memory['confirmed_requirements'] else '-'}",
        f"- disliked_patterns: {', '.join(memory['disliked_patterns']) if memory['disliked_patterns'] else '-'}",
        f"- next_priorities: {', '.join(memory['next_priorities']) if memory['next_priorities'] else '-'}",
        f"- todo: {', '.join(memory['todo']) if memory['todo'] else '-'}",
        f"- version_history_count: {memory['version_history_count']}",
        "",
        "## Latest Regression",
        "",
        f"- path: {regression['path']}",
        f"- profile: {regression['profile']}",
        f"- overall_ok: {regression['overall_ok']}",
        f"- aggregate: {json.dumps(regression['aggregate'], ensure_ascii=False)}",
        "",
        "## Artifacts",
        "",
        f"- latest_backup: {artifacts['latest_backup']}",
        f"- latest_regression_report: {artifacts['latest_regression_report']}",
        f"- latest_output_dir: {artifacts['latest_output_dir']}",
    ]
    return "\n".join(lines) + "\n"


def main() -> None:
    DIAGNOSTICS_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    report = build_report()
    json_path = DIAGNOSTICS_DIR / f"diagnostics_{timestamp}.json"
    md_path = DIAGNOSTICS_DIR / f"diagnostics_{timestamp}.md"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(render_markdown(report), encoding="utf-8")
    print(
        json.dumps(
            {
                "ok": True,
                "json_path": str(json_path),
                "markdown_path": str(md_path),
                "git_head": report["git"]["head"],
                "latest_regression": report["latest_regression"]["path"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
