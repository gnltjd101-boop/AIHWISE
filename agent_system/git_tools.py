from __future__ import annotations

import subprocess
import time
from pathlib import Path
from typing import Any

from .paths import ROOT_DIR


def _run_git(args: list[str], cwd: Path | None = None) -> tuple[int, str, str]:
    workdir = str(cwd or ROOT_DIR)
    try:
        completed = subprocess.run(
            ["git", *args],
            cwd=workdir,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=15,
            check=False,
        )
    except Exception as exc:
        return 1, "", str(exc)
    return completed.returncode, completed.stdout.strip(), completed.stderr.strip()


def is_git_repo(root: Path | None = None) -> bool:
    code, stdout, _ = _run_git(["rev-parse", "--is-inside-work-tree"], root)
    return code == 0 and stdout.lower() == "true"


def ensure_git_repository(root: Path | None = None) -> dict[str, Any]:
    repo_root = root or ROOT_DIR
    initialized_now = False
    if not is_git_repo(repo_root):
        code, _, stderr = _run_git(["init"], repo_root)
        if code != 0:
            return {
                "enabled": False,
                "initialized_now": False,
                "error": stderr or "git init failed",
                "root": str(repo_root),
                "timestamp": time.time(),
            }
        initialized_now = True
    status = get_git_status(repo_root)
    status["initialized_now"] = bool(initialized_now or status.get("initialized_now"))
    return status


def get_git_status(root: Path | None = None) -> dict[str, Any]:
    repo_root = root or ROOT_DIR
    if not is_git_repo(repo_root):
        return {
            "enabled": False,
            "root": str(repo_root),
            "timestamp": time.time(),
        }

    branch = ""
    dirty_files: list[str] = []
    status_code, status_stdout, status_stderr = _run_git(["status", "--short", "--branch"], repo_root)
    if status_code == 0:
        lines = [line for line in status_stdout.splitlines() if line.strip()]
        if lines and lines[0].startswith("##"):
            branch = lines[0][2:].strip()
            dirty_files = lines[1:]
        else:
            dirty_files = lines

    head_code, head_stdout, _ = _run_git(["rev-parse", "--short", "HEAD"], repo_root)
    head = head_stdout if head_code == 0 else ""

    remote_code, remote_stdout, _ = _run_git(["remote", "-v"], repo_root)
    remotes: list[str] = []
    if remote_code == 0 and remote_stdout:
        seen: set[str] = set()
        for line in remote_stdout.splitlines():
            line = line.strip()
            if not line:
                continue
            name = line.split()[0]
            if name not in seen:
                seen.add(name)
                remotes.append(line)

    return {
        "enabled": True,
        "root": str(repo_root),
        "branch": branch,
        "head": head,
        "dirty": bool(dirty_files),
        "dirty_files": dirty_files[:20],
        "remotes": remotes[:10],
        "status_error": status_stderr,
        "timestamp": time.time(),
    }


def summarize_git_status(git_info: dict[str, Any] | None) -> str:
    if not git_info or not git_info.get("enabled"):
        return ""
    parts: list[str] = []
    if git_info.get("branch"):
        parts.append(f"branch={git_info['branch']}")
    if git_info.get("head"):
        parts.append(f"head={git_info['head']}")
    parts.append("dirty=yes" if git_info.get("dirty") else "dirty=no")
    if git_info.get("initialized_now"):
        parts.append("initialized_now=yes")
    return " / ".join(parts)
