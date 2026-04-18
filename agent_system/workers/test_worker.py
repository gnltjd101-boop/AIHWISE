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


def collect_text_blobs(output_dir: Path) -> dict[str, str]:
    blobs: dict[str, str] = {}
    for path in output_dir.rglob("*"):
        if not path.is_file():
            continue
        if "__pycache__" in path.parts or "_upgrades" in path.parts:
            continue
        if path.suffix.lower() not in {".py", ".js", ".html", ".css", ".md", ".txt", ".json"}:
            continue
        try:
            relative = str(path.relative_to(output_dir)).replace("\\", "/")
            blobs[relative] = path.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
    return blobs


def check_feedback_alignment(output_dir: Path, implementation: dict[str, Any]) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    text_blobs = collect_text_blobs(output_dir)
    combined = "\n".join(f"{path}\n{content}" for path, content in text_blobs.items()).lower()
    file_names = [path.lower() for path in text_blobs]
    confirmed_requirements = [str(item).strip() for item in implementation.get("confirmed_requirements") or [] if str(item).strip()]
    disliked_patterns = [str(item).strip() for item in implementation.get("disliked_patterns") or [] if str(item).strip()]

    for requirement in confirmed_requirements[:6]:
        status = "ok"
        note = "요구사항이 구현 메타데이터에 기록되어 있습니다."
        lowered = requirement.lower()
        if "로그" in requirement or "log" in lowered:
            matched = any(token in combined or token in " ".join(file_names) for token in ("로그", "log", "logging"))
            status = "ok" if matched else "error"
            note = "로그 관련 파일/문구를 찾았습니다." if matched else "로그 관련 구조를 결과물에서 찾지 못했습니다."
        elif "대시보드" in requirement:
            matched = any(name.endswith("index.html") for name in file_names)
            status = "ok" if matched else "error"
            note = "대시보드용 HTML 진입점을 찾았습니다." if matched else "대시보드용 HTML 진입점을 찾지 못했습니다."
        elif "앱" in requirement:
            matched = any(name.endswith(("index.html", "main.py")) for name in file_names)
            status = "ok" if matched else "error"
            note = "앱 진입점을 찾았습니다." if matched else "앱 진입점을 찾지 못했습니다."
        checks.append({"name": f"feedback requirement: {requirement[:40]}", "status": status, "note": note})

    for pattern in disliked_patterns[:4]:
        lowered = pattern.lower()
        if "파일 하나" in pattern or "one file" in lowered:
            code_files = [
                name
                for name in file_names
                if name.endswith((".py", ".js", ".html"))
            ]
            status = "ok" if len(code_files) >= 2 else "error"
            note = "핵심 코드 파일이 분리되어 있습니다." if status == "ok" else "핵심 코드 파일이 한 파일에 과도하게 몰려 있을 수 있습니다."
            checks.append({"name": f"feedback dislike: {pattern[:40]}", "status": status, "note": note})
        else:
            checks.append({"name": f"feedback dislike: {pattern[:40]}", "status": "ok", "note": "싫어한 방식 메타데이터를 확인했습니다."})
    return checks


def check_structure_rules(implementation: dict[str, Any]) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    rules = [str(item).strip() for item in implementation.get("structure_rules") or [] if str(item).strip()]
    written_files = [str(item).replace("\\", "/").lower() for item in implementation.get("written_files") or []]
    if not rules:
        return checks
    if any("index.html" in rule for rule in rules):
        required = ("index.html", "styles.css", "app.js")
        missing = [name for name in required if not any(path.endswith(name) for path in written_files)]
        checks.append(
            {
                "name": "structure rule: web entry set",
                "status": "ok" if not missing else "error",
                "note": "웹 기본 진입 파일 구성이 맞습니다." if not missing else f"누락 파일: {', '.join(missing)}",
            }
        )
    if any("main.py" in rule for rule in rules):
        checks.append(
            {
                "name": "structure rule: python main entry",
                "status": "ok" if any(path.endswith("main.py") for path in written_files) else "error",
                "note": "main.py 엔트리포인트를 찾았습니다." if any(path.endswith("main.py") for path in written_files) else "main.py 엔트리포인트를 찾지 못했습니다.",
            }
        )
    return checks


def run_project_checks(output_dir: Path, implementation: dict[str, Any]) -> dict[str, Any]:
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

    checks.extend(check_feedback_alignment(output_dir, implementation))
    checks.extend(check_structure_rules(implementation))

    for check in checks:
        if check.get("status") != "ok":
            failures.append(check)
    return {"checks": checks, "failures": failures}


def run_checks(output_dir: Path, written_files: list[str], implementation: dict[str, Any] | None = None) -> dict[str, Any]:
    implementation = implementation or {}
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

    project_checks = run_project_checks(output_dir, implementation)
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
            JobStep(name="run_checks", status="running", note="기본 문법과 실행 검증을 수행합니다."),
            JobStep(name="failure_summary", status="pending", note="실패가 있으면 요약을 만듭니다."),
        ]
        job.summary = "테스트 작업이 기본 검증을 수행하고 있습니다."

        try:
            payload = job.metadata.get("implementation") or job.result or {}
            output_dir = Path(str(payload.get("output_dir") or ""))
            written_files = [str(item) for item in payload.get("written_files") or []]
            report = run_checks(output_dir, written_files, payload)
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
