from __future__ import annotations

import json
import os
from pathlib import Path
import re
import shutil
import socket
import subprocess
import time
import urllib.request
from typing import Any

from ..models import AgentJob, JobStep


def find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def wait_for_http(url: str, attempts: int = 14, delay_s: float = 0.8) -> tuple[bool, str]:
    body_preview = ""
    for _ in range(attempts):
        try:
            with urllib.request.urlopen(url, timeout=5) as response:
                body_preview = response.read(1200).decode("utf-8", errors="replace")
                if response.status == 200:
                    return True, body_preview[:500]
        except Exception:
            time.sleep(delay_s)
    return False, body_preview


def discover_python_entrypoint(output_dir: Path) -> Path | None:
    for relative in ("app.py", "main.py", "server.py", "__main__.py", "src/main.py", "src/app.py"):
        candidate = output_dir / relative
        if candidate.exists():
            return candidate
    return None


def inspect_python_entrypoint(output_dir: Path, entry_path: Path) -> dict[str, Any]:
    source = entry_path.read_text(encoding="utf-8", errors="replace")
    requirements = (output_dir / "requirements.txt").read_text(encoding="utf-8", errors="replace").lower() if (output_dir / "requirements.txt").exists() else ""
    lower_source = source.lower()
    if "fastapi" in lower_source or "fastapi" in requirements:
        app_match = re.search(r"^\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*=\s*FastAPI\s*\(", source, re.MULTILINE)
        app_name = app_match.group(1) if app_match else "app"
        module_name = ".".join(entry_path.relative_to(output_dir).with_suffix("").parts)
        return {"mode": "python_web", "runner": "uvicorn", "module_name": module_name, "app_name": app_name}
    if "flask" in lower_source or "flask" in requirements:
        app_match = re.search(r"^\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*=\s*Flask\s*\(", source, re.MULTILINE)
        app_name = app_match.group(1) if app_match else "app"
        module_name = ".".join(entry_path.relative_to(output_dir).with_suffix("").parts)
        return {"mode": "python_web", "runner": "flask", "module_name": module_name, "app_name": app_name}
    if "http.server" in lower_source or "socketserver" in lower_source:
        return {"mode": "python_web", "runner": "python", "module_name": None, "app_name": None}
    return {"mode": "python_cli", "runner": "python"}


def detect_run_mode(output_dir: Path) -> dict[str, Any]:
    package_json = output_dir / "package.json"
    index_html = output_dir / "index.html"
    if package_json.exists():
        try:
            package = json.loads(package_json.read_text(encoding="utf-8", errors="replace"))
        except json.JSONDecodeError:
            package = {}
        scripts = package.get("scripts") or {}
        if "dev" in scripts:
            return {"mode": "node_dev", "entry_point": str(package_json), "script": "dev"}
        if "start" in scripts:
            return {"mode": "node_start", "entry_point": str(package_json), "script": "start"}
    if index_html.exists():
        return {"mode": "static_server", "entry_point": str(index_html)}
    python_entry = discover_python_entrypoint(output_dir)
    if python_entry is not None:
        detected = inspect_python_entrypoint(output_dir, python_entry)
        detected["entry_point"] = str(python_entry)
        return detected
    raise RuntimeError(f"실행 가능한 엔트리포인트를 찾지 못했습니다: {output_dir}")


def run_static_site(output_dir: Path) -> dict[str, Any]:
    port = find_free_port()
    process = subprocess.Popen(
        ["python", "-m", "http.server", str(port), "--bind", "127.0.0.1"],
        cwd=str(output_dir),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        url = f"http://127.0.0.1:{port}/"
        ok, body_preview = wait_for_http(url)
        if not ok:
            stderr_text = process.stderr.read() if process.stderr else ""
            raise RuntimeError(f"정적 서버 응답 확인 실패: {stderr_text}")
        return {"mode": "static_server", "url": url, "body_preview": body_preview}
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()


def run_python_cli(output_dir: Path, entry_point: str) -> dict[str, Any]:
    entry = Path(entry_point)
    command_target = str(entry.relative_to(output_dir)) if entry.is_absolute() else str(entry)
    completed = subprocess.run(
        ["python", command_target, "--help"],
        cwd=str(output_dir),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=90,
    )
    output = ((completed.stdout or "") + "\n" + (completed.stderr or "")).strip()
    if completed.returncode != 0:
        raise RuntimeError(output[:500] or f"CLI exited with {completed.returncode}")
    return {"mode": "python_cli", "entry_point": entry_point, "stdout_preview": output[:500]}


def run_python_web(output_dir: Path, entry_point: str, runner: str, module_name: str | None, app_name: str | None) -> dict[str, Any]:
    port = find_free_port()
    env = os.environ.copy()
    env["PORT"] = str(port)
    env["HOST"] = "127.0.0.1"
    entry = Path(entry_point)
    command_target = str(entry.relative_to(output_dir)) if entry.is_absolute() else str(entry)

    if runner == "uvicorn":
        args = ["python", "-m", "uvicorn", f"{module_name or 'app'}:{app_name or 'app'}", "--host", "127.0.0.1", "--port", str(port)]
    elif runner == "flask":
        env["FLASK_APP"] = f"{module_name or 'app'}:{app_name or 'app'}"
        args = ["python", "-m", "flask", "run", "--host", "127.0.0.1", "--port", str(port)]
    else:
        args = ["python", command_target]

    process = subprocess.Popen(
        args,
        cwd=str(output_dir),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        url = f"http://127.0.0.1:{port}/"
        ok, body_preview = wait_for_http(url)
        if not ok:
            stderr_text = process.stderr.read() if process.stderr else ""
            raise RuntimeError(f"Python 웹 실행 확인 실패: {stderr_text}")
        return {"mode": "python_web", "runner": runner, "url": url, "body_preview": body_preview}
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()


def run_node_app(output_dir: Path, script: str) -> dict[str, Any]:
    if not shutil.which("npm"):
        raise RuntimeError("npm을 찾지 못했습니다.")
    if not (output_dir / "node_modules").exists():
        install = subprocess.run(
            ["npm", "install"],
            cwd=str(output_dir),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=180,
        )
        if install.returncode != 0:
            raise RuntimeError(((install.stdout or "") + "\n" + (install.stderr or "")).strip()[:500])
    port = find_free_port()
    env = os.environ.copy()
    env["PORT"] = str(port)
    env["HOST"] = "127.0.0.1"
    args = ["npm", "run", script]
    if script == "dev":
        args += ["--", "--host", "127.0.0.1", "--port", str(port)]
    process = subprocess.Popen(args, cwd=str(output_dir), env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        url = f"http://127.0.0.1:{port}/"
        ok, body_preview = wait_for_http(url, attempts=18, delay_s=1.0)
        if not ok:
            stderr_text = process.stderr.read() if process.stderr else ""
            raise RuntimeError(f"Node 실행 확인 실패: {stderr_text}")
        return {"mode": f"node_{script}", "url": url, "body_preview": body_preview}
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()


def run_detected_target(output_dir: Path) -> dict[str, Any]:
    detected = detect_run_mode(output_dir)
    mode = detected["mode"]
    if mode == "static_server":
        return run_static_site(output_dir)
    if mode == "python_cli":
        return run_python_cli(output_dir, detected["entry_point"])
    if mode == "python_web":
        return run_python_web(output_dir, detected["entry_point"], str(detected.get("runner") or "python"), detected.get("module_name"), detected.get("app_name"))
    if mode in {"node_dev", "node_start"}:
        return run_node_app(output_dir, detected["script"])
    raise RuntimeError(f"지원하지 않는 실행 모드입니다: {mode}")


class RunWorker:
    name = "run_worker"

    def can_handle(self, job: AgentJob) -> bool:
        return job.category == "run"

    def process(self, job: AgentJob) -> AgentJob:
        job.assigned_worker = self.name
        job.stage = "run"
        job.status = "running"
        job.steps = [
            JobStep(name="run_target_scan", status="done", note="실행 가능한 엔트리포인트를 찾고 있습니다."),
            JobStep(name="launch_target", status="running", note="결과물을 실제로 실행해 봅니다."),
            JobStep(name="probe_result", status="pending", note="응답 또는 종료 코드를 확인합니다."),
        ]
        job.summary = "런너가 결과물을 실행하고 있습니다."

        try:
            implementation = job.metadata.get("implementation") or job.result or {}
            output_dir = Path(str(implementation.get("output_dir") or ""))
            run_result = run_detected_target(output_dir)
            job.result = run_result
            job.status = "done"
            job.summary = "결과물을 실행하고 응답을 확인했습니다."
            job.steps[1].status = "done"
            job.steps[1].note = run_result.get("url") or run_result.get("stdout_preview") or run_result.get("mode", "")
            job.steps[1].updated_at = time.time()
            job.steps[2].status = "done"
            job.steps[2].note = "실행 결과를 상태 파일에 기록했습니다."
            job.steps[2].updated_at = time.time()
        except Exception as exc:
            job.status = "error"
            job.summary = f"실행 단계에서 오류가 발생했습니다: {exc}"
            job.result = {"error": str(exc)}
            job.steps[1].status = "error"
            job.steps[1].note = str(exc)
            job.steps[1].updated_at = time.time()

        return job
