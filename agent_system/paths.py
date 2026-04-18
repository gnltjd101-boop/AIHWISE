from __future__ import annotations

from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parent.parent
COMMAND_PATH = ROOT_DIR / "OPEN_ME_COMMAND.txt"
STATUS_PATH = ROOT_DIR / "OPEN_ME_STATUS.json"
JOB_STATE_PATH = ROOT_DIR / "agent_job_state.json"
STATE_PATH = JOB_STATE_PATH
HISTORY_PATH = ROOT_DIR / "agent_chat_history.jsonl"
META_PATH = ROOT_DIR / "agent_chat_meta.json"
JOBS_PATH = ROOT_DIR / "agent_jobs.jsonl"
PROJECTS_DIR = ROOT_DIR / "agent_projects"
ACTIVE_PROJECT_PATH = ROOT_DIR / "agent_active_project.json"
OUTPUT_DIR = ROOT_DIR / "agent_outputs"
