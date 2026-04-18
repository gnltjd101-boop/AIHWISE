from __future__ import annotations

import ast
import json
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

from ..models import AgentJob, JobStep


def validate_file(path: Path) -> dict[str, Any]:
    suffix = path.suffix.lower()
    content = path.read_text(encoding="utf-8", errors="replace")
    if suffix == ".py":
        ast.parse(content)
        return {"path": str(path), "status": "ok", "note": "Python 문법 검사 통과"}
    if suffix == ".json":
        json.loads(content)
        return {"path": str(path), "status": "ok", "note": "JSON 문법 검사 통과"}
    if suffix in {".html", ".css", ".js", ".md", ".txt"}:
        return {"path": str(path), "status": "ok", "note": f"{suffix} 파일 확인"}
    return {"path": str(path), "status": "ok", "note": "파일 존재 확인"}


def run_command_check(command: list[str], cwd: Path, name: str, timeout: int = 180) -> dict[str, Any]:
    try:
        completed = subprocess.run(
            command,
            cwd=str(cwd),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=timeout,
        )
    except Exception as exc:
        return {"name": name, "status": "error", "note": str(exc)}

    output = ((completed.stdout or "") + "\n" + (completed.stderr or "")).strip()
    if completed.returncode == 0:
        return {"name": name, "status": "ok", "note": output[:300] or "success"}
    return {"name": name, "status": "error", "note": output[:300] or f"exit code {completed.returncode}"}


def run_project_checks(output_dir: Path) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []

    package_json = output_dir / "package.json"
    index_html = output_dir / "index.html"
    main_py = output_dir / "main.py"
    smoke_test = output_dir / "smoke_test.py"
    project_spec = output_dir / "project_spec.json"

    if package_json.exists() and shutil.which("npm"):
        try:
            package = json.loads(package_json.read_text(encoding="utf-8", errors="replace"))
        except json.JSONDecodeError as exc:
            failures.append({"name": "package.json parse", "status": "error", "note": str(exc)})
            package = {}
        scripts = package.get("scripts") or {}
        if "build" in scripts:
            checks.append(run_command_check(["npm", "run", "build"], output_dir, "npm run build", timeout=240))
        if "test" in scripts:
            checks.append(run_command_check(["npm", "run", "test", "--", "--runInBand"], output_dir, "npm run test", timeout=240))

    if main_py.exists():
        checks.append(run_command_check(["python", "main.py", "--help"], output_dir, "python main.py --help", timeout=120))

    if smoke_test.exists():
        checks.append(run_command_check(["python", "smoke_test.py"], output_dir, "python smoke_test.py", timeout=120))

    if project_spec.exists():
        try:
            spec = json.loads(project_spec.read_text(encoding="utf-8", errors="replace"))
            if spec.get("title") and spec.get("goal"):
                checks.append({"name": "project_spec shape", "status": "ok", "note": "title/goal 필드 확인"})
            else:
                failures.append({"name": "project_spec shape", "status": "error", "note": "title 또는 goal 필드가 비어 있습니다."})
        except json.JSONDecodeError as exc:
            failures.append({"name": "project_spec shape", "status": "error", "note": str(exc)})

    if index_html.exists():
        content = index_html.read_text(encoding="utf-8", errors="replace").lower()
        if "<body" in content and "</html>" in content:
            checks.append({"name": "static html structure", "status": "ok", "note": "HTML 기본 구조 확인"})
        else:
            failures.append({"name": "static html structure", "status": "error", "note": "index.html 기본 구조가 불완전합니다."})

    for check in checks:
        if check.get("status") != "ok":
            failures.append(check)
    return {"checks": checks, "failures": failures}


def run_checks(output_dir: Path, written_files: list[str]) -> dict[str, Any]:
    results: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    if not output_dir.exists():
        raise RuntimeError(f"출력 폴더가 없습니다: {output_dir}")

    for raw_path in written_files:
        path = Path(raw_path)
        if not path.exists():
            failures.append({"path": str(path), "status": "error", "note": "파일이 존재하지 않습니다."})
            continue
        try:
            results.append(validate_file(path))
        except Exception as exc:
            failures.append({"path": str(path), "status": "error", "note": str(exc)})

    project_checks = run_project_checks(output_dir)
    failures.extend(project_checks["failures"])
    return {
        "checked": len(results) + len(failures),
        "passed": len(results),
        "failed": len(failures),
        "results": results,
        "failures": failures,
        "project_checks": project_checks["checks"],
    }


class TestWorker:
    name = "test_worker"

    def can_handle(self, job: AgentJob) -> bool:
        return job.category == "test"

    def process(self, job: AgentJob) -> AgentJob:
        job.assigned_worker = self.name
        job.stage = "test"
        job.status = "running"
        job.steps = [
            JobStep(name="test_target_scan", status="done", note="출력 경로와 파일 목록을 확인했습니다."),
            JobStep(name="run_checks", status="running", note="기본 문법 및 실행 검증을 수행합니다."),
            JobStep(name="failure_summary", status="pending", note="실패가 있으면 요약을 만듭니다."),
        ]
        job.summary = "테스트 작업이 기본 검증을 수행하고 있습니다."

        try:
            payload = job.metadata.get("implementation") or job.result or {}
            output_dir = Path(str(payload.get("output_dir") or ""))
            written_files = [str(item) for item in payload.get("written_files") or []]
            report = run_checks(output_dir, written_files)
            job.result = report
            job.status = "done" if int(report["failed"]) == 0 else "error"
            job.summary = f"테스트 완료: 통과 {report['passed']}건 / 실패 {report['failed']}건"
            job.steps[1].status = "done" if job.status == "done" else "error"
            job.steps[1].note = job.summary
            job.steps[1].updated_at = time.time()
            job.steps[2].status = "done"
            job.steps[2].note = "실패 항목을 포함한 테스트 보고서를 저장했습니다."
            job.steps[2].updated_at = time.time()
        except Exception as exc:
            job.status = "error"
            job.summary = f"테스트 단계에서 오류가 발생했습니다: {exc}"
            job.result = {"error": str(exc)}
            job.steps[1].status = "error"
            job.steps[1].note = str(exc)
            job.steps[1].updated_at = time.time()

        return job
