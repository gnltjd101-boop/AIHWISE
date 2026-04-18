from __future__ import annotations

import json
import os
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from agent_system.git_tools import summarize_git_status
from agent_system.interpreter import should_route_to_operator
from agent_system.memory_manager import apply_user_feedback
from agent_system.orchestrator import run_once as run_orchestrator_once
from agent_system.paths import HISTORY_PATH, META_PATH, STATUS_PATH
from agent_system.queue_store import (
    clear_active_project,
    delete_project_memory,
    read_active_project,
    read_project_memory,
    read_state as read_job_state,
)
from agent_system.workers.openai_common import safe_text_response


HOST = "127.0.0.1"
PORT = int(os.environ.get("AGENT_CHAT_PORT", "8780"))
CHAT_MODEL = os.environ.get("AGENT_CHAT_MODEL", "gpt-5.4-mini")
CHAT_REASONING_EFFORT = os.environ.get("AGENT_CHAT_REASONING_EFFORT", "low")


HTML = """<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>AI 에이전트 채팅</title>
  <style>
    :root {
      --bg: #f4efe6;
      --panel: #fffaf2;
      --line: #d7ccb8;
      --text: #1f1a17;
      --muted: #6d6258;
      --user: #dcecff;
      --agent: #efe4d1;
      --accent: #1d5c4b;
      --danger: #a33636;
      --warn: #8a5a16;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      background: linear-gradient(180deg, #efe7d8 0%, #f8f4ed 100%);
      color: var(--text);
      font: 16px/1.5 "Malgun Gothic", sans-serif;
    }
    .wrap {
      max-width: 980px;
      margin: 0 auto;
      min-height: 100vh;
      display: grid;
      grid-template-rows: auto auto 1fr auto;
      gap: 12px;
      padding: 18px;
    }
    .panel {
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 18px;
      box-shadow: 0 10px 30px rgba(65, 49, 31, 0.08);
    }
    .top, .status, .composer { padding: 16px 18px; }
    .top h1 { margin: 0 0 6px; font-size: 24px; }
    .top p, .hint, .meta, .label { color: var(--muted); }
    .status { display: flex; gap: 12px; align-items: center; flex-wrap: wrap; }
    .badge {
      display: inline-flex;
      align-items: center;
      border-radius: 999px;
      padding: 6px 10px;
      font-size: 13px;
      font-weight: 700;
      background: #e5efe9;
      color: var(--accent);
    }
    .badge.running { background: #fff0d5; color: var(--warn); }
    .badge.error { background: #f8dddd; color: var(--danger); }
    .chat {
      background: rgba(255,255,255,0.48);
      border: 1px solid rgba(215, 204, 184, 0.7);
      border-radius: 22px;
      padding: 16px;
      overflow: auto;
      min-height: 420px;
    }
    .msg {
      max-width: 86%;
      margin-bottom: 12px;
      padding: 12px 14px;
      border-radius: 18px;
      white-space: pre-wrap;
      word-break: break-word;
      border: 1px solid rgba(0,0,0,0.04);
    }
    .msg.user { margin-left: auto; background: var(--user); }
    .msg.agent { margin-right: auto; background: var(--agent); }
    textarea {
      width: 100%;
      min-height: 88px;
      resize: vertical;
      border: 1px solid var(--line);
      border-radius: 14px;
      padding: 12px;
      font: inherit;
      background: #fffdf8;
      color: var(--text);
    }
    .actions {
      margin-top: 10px;
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 12px;
    }
    button {
      border: 0;
      border-radius: 12px;
      padding: 12px 16px;
      font: inherit;
      font-weight: 700;
      cursor: pointer;
    }
    .send { background: var(--accent); color: white; }
    .clear { background: #ede4d6; color: var(--text); }
  </style>
</head>
<body>
  <div class="wrap">
    <div class="panel top">
      <h1>AI 에이전트 채팅</h1>
      <p>아이디어를 입력하면 조사, 코딩, 실행, 테스트, 리뷰까지 이어서 처리합니다.</p>
    </div>
    <div class="panel status">
      <span id="badge" class="badge">대기 중</span>
      <span class="label">현재 작업:</span>
      <span id="currentCommand">없음</span>
    </div>
    <div id="chat" class="chat"></div>
    <div class="panel composer">
      <textarea id="input" placeholder="예: 업비트/빗썸 시세차익 대시보드 만들어&#10;예: 현재 프로젝트 고도화해&#10;예: 현재 프로젝트 확인"></textarea>
      <div class="actions">
        <div class="hint">Enter 전송 / Shift+Enter 줄바꿈</div>
        <div>
          <button class="clear" id="clearBtn" type="button">대화 비우기</button>
          <button class="send" id="sendBtn" type="button">보내기</button>
        </div>
      </div>
    </div>
  </div>
  <script>
    const chatEl = document.getElementById("chat");
    const inputEl = document.getElementById("input");
    const badgeEl = document.getElementById("badge");
    const currentCommandEl = document.getElementById("currentCommand");

    function statusLabel(value) {
      return {
        idle: "대기 중",
        running: "작업 중",
        done: "완료",
        error: "오류",
      }[value] || value || "상태 없음";
    }

    function formatTime(ts) {
      if (!ts) return "";
      const d = new Date(ts * 1000);
      return d.toLocaleString("ko-KR");
    }

    function renderMessages(items) {
      chatEl.innerHTML = "";
      for (const item of items) {
        const box = document.createElement("div");
        box.className = "msg " + item.role;
        box.textContent = item.text || "";
        const meta = document.createElement("div");
        meta.className = "meta";
        meta.textContent = (item.role === "user" ? "사용자" : "에이전트") + " · " + formatTime(item.timestamp);
        box.appendChild(meta);
        chatEl.appendChild(box);
      }
      chatEl.scrollTop = chatEl.scrollHeight;
    }

    async function refresh() {
      const res = await fetch("/api/state");
      const data = await res.json();
      renderMessages(data.messages || []);
      const status = data.status || {};
      const stateValue = status.status || "idle";
      badgeEl.textContent = statusLabel(stateValue);
      badgeEl.className = "badge " + stateValue + (stateValue === "error" ? " error" : "");
      currentCommandEl.textContent = status.command || "없음";
      document.title = statusLabel(stateValue) + " · AI 에이전트 채팅";
    }

    async function sendMessage() {
      const text = inputEl.value.trim();
      if (!text) return;
      await fetch("/api/message", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text })
      });
      inputEl.value = "";
      await refresh();
    }

    async function clearMessages() {
      await fetch("/api/clear", { method: "POST" });
      await refresh();
    }

    document.getElementById("sendBtn").addEventListener("click", sendMessage);
    document.getElementById("clearBtn").addEventListener("click", clearMessages);
    inputEl.addEventListener("keydown", (event) => {
      if (event.key === "Enter" && !event.shiftKey) {
        event.preventDefault();
        sendMessage();
      }
    });

    refresh();
    setInterval(refresh, 2000);
  </script>
</body>
</html>
"""


def read_text_with_fallback(path: Path) -> str:
    if not path.exists():
        return ""
    for encoding in ("utf-8", "utf-8-sig", "cp949"):
        try:
            return path.read_text(encoding=encoding)
        except UnicodeDecodeError:
            continue
    return path.read_text(encoding="utf-8", errors="replace")


def read_json(path: Path) -> dict[str, Any]:
    raw = read_text_with_fallback(path).strip()
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def append_jsonl(path: Path, entry: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, ensure_ascii=False) + "\n")


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    items: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            parsed = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            items.append(parsed)
    return items


def load_meta() -> dict[str, Any]:
    return read_json(META_PATH)


def save_meta(meta: dict[str, Any]) -> None:
    META_PATH.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")


def parse_jsonish(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    text = str(value or "").strip()
    if not text:
        return {}
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def handle_project_command(text: str) -> str | None:
    command = text.strip()
    if command == "현재 프로젝트 확인":
        active = read_active_project()
        if not active:
            return "현재 활성 프로젝트가 없습니다."
        project_id = str(active.get("project_id") or "").strip()
        memory = read_project_memory(project_id) if project_id else {}
        lines = ["현재 프로젝트 정보:"]
        if active.get("title"):
            lines.append(f"- 프로젝트: {active['title']}")
        if project_id:
            lines.append(f"- 프로젝트 ID: {project_id}")
        if active.get("latest_output_dir"):
            lines.append(f"- 최근 결과물 위치: {active['latest_output_dir']}")
        if memory.get("project_type"):
            lines.append(f"- 프로젝트 유형: {memory['project_type']}")
        if memory.get("current_goal"):
            lines.append(f"- 현재 목표: {memory['current_goal']}")
        git_summary = summarize_git_status(memory.get("git"))
        if git_summary:
            lines.append(f"- Git: {git_summary}")
        if memory.get("recent_failure_causes"):
            lines.append("- 최근 실패 원인:")
            lines.extend(f"  - {item}" for item in memory["recent_failure_causes"][:4])
        return "\n".join(lines)
    if command == "새 프로젝트로 시작":
        clear_active_project()
        return "현재 활성 프로젝트를 해제했습니다. 다음 요청은 새 프로젝트로 처리합니다."
    if command == "현재 프로젝트 초기화":
        active = read_active_project()
        project_id = str(active.get("project_id") or "").strip()
        deleted = delete_project_memory(project_id) if project_id else False
        clear_active_project()
        if project_id and deleted:
            return f"현재 프로젝트 메모리를 초기화했습니다. ({project_id})"
        return "현재 활성 프로젝트를 초기화했습니다."
    feedback_result = apply_user_feedback(command)
    if feedback_result:
        return feedback_result
    return None


def call_fast_chat(user_text: str) -> str:
    history = load_jsonl(HISTORY_PATH)[-8:]
    response = safe_text_response(
        developer_text=(
            "You are a concise Korean assistant inside a local desktop AI agent UI. "
            "Reply naturally in Korean. "
            "If the user asks for a task that should be executed by the local operator, say that the task will be handed off."
        ),
        user_payload={
            "history": history,
            "user_text": user_text,
        },
        model=CHAT_MODEL,
        reasoning_effort=CHAT_REASONING_EFFORT,
    )
    if response:
        return response
    return "일반 대화 모드입니다. 실행이 필요한 요청이면 그대로 보내면 작업 에이전트가 이어서 처리합니다."


def format_attempt(attempt: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    implementation = parse_jsonish(attempt.get("implementation"))
    run_result = parse_jsonish(attempt.get("run"))
    test_result = parse_jsonish(attempt.get("test"))
    review = parse_jsonish(attempt.get("review"))
    if implementation.get("output_dir"):
        lines.append(f"- 결과물 위치: {implementation['output_dir']}")
    if implementation.get("app_type"):
        lines.append(f"- 결과 유형: {implementation['app_type']}")
    if implementation.get("stack"):
        lines.append(f"- 스택: {implementation['stack']}")
    if implementation.get("upgrade_candidate"):
        lines.append(f"- 선택된 업그레이드 후보: {implementation['upgrade_candidate']}")
    if run_result.get("url"):
        lines.append(f"- 실행 URL: {run_result['url']}")
    if run_result.get("stdout_preview"):
        lines.append(f"- 실행 출력: {run_result['stdout_preview'][:180]}")
    if run_result.get("error"):
        lines.append(f"- 실행 오류: {run_result['error'][:180]}")
    if test_result:
        lines.append(f"- 테스트: 통과 {test_result.get('passed', 0)} / 실패 {test_result.get('failed', 0)}")
    if review.get("summary"):
        lines.append(f"- 리뷰: {review['summary']}")
    return lines


def pretty_print_job_result(state: dict[str, Any]) -> str:
    result = parse_jsonish(state.get("result"))
    if not result:
        return str(state.get("summary") or "")
    interpretation = result.get("interpretation") or {}
    grade = result.get("grade") or {}
    best_attempt = result.get("best_attempt") or {}
    project_memory = result.get("project_memory") or {}
    git_info = result.get("git") or project_memory.get("git") or {}
    lines = ["작업 결과:"]
    if interpretation.get("goal_summary"):
        lines.append(f"- 목표: {interpretation['goal_summary']}")
    if interpretation.get("domain_mode"):
        lines.append(f"- 유형: {interpretation['domain_mode']}")
    if grade:
        lines.append(f"- 평가: {grade.get('status', '')} / 점수 {grade.get('score', 0)}")
    lines.extend(format_attempt(best_attempt))
    if project_memory.get("latest_output_dir"):
        lines.append(f"- 프로젝트 메모리 기준 출력 위치: {project_memory['latest_output_dir']}")
    git_summary = summarize_git_status(git_info)
    if git_summary:
        lines.append(f"- Git: {git_summary}")
    parallel_upgrades = result.get("parallel_upgrades") or {}
    recommended_upgrade = parallel_upgrades.get("recommended") or {}
    best_executed = parallel_upgrades.get("best_executed") or {}
    if recommended_upgrade.get("name"):
        lines.append(f"- 추천 병렬 업그레이드: {recommended_upgrade['name']} / {recommended_upgrade.get('goal', '')}")
    if best_executed.get("name"):
        grade_info = best_executed.get("grade") or {}
        lines.append(f"- 실제 선택된 후보: {best_executed['name']} / 점수 {grade_info.get('score', 0)}")
    pipeline = result.get("pipeline") or state.get("pipeline") or []
    if pipeline:
        lines.append("- 최근 파이프라인:")
        for item in pipeline[-8:]:
            lines.append(f"  - {item.get('category', '')}: {item.get('status', '')} / {item.get('summary', '')}")
    return "\n".join(lines)


def sync_assistant_messages() -> None:
    status = read_json(STATUS_PATH)
    history = load_jsonl(HISTORY_PATH)
    meta = load_meta()
    response_id = str(status.get("response_id") or "")
    summary = str(status.get("human_summary") or "").strip()
    if not response_id or not summary:
        return
    if response_id == str(meta.get("last_synced_response_id") or ""):
        return
    history.append({"role": "agent", "text": summary, "timestamp": time.time(), "response_id": response_id})
    HISTORY_PATH.write_text("\n".join(json.dumps(item, ensure_ascii=False) for item in history) + ("\n" if history else ""), encoding="utf-8")
    meta["last_synced_response_id"] = response_id
    save_meta(meta)


def sync_job_messages() -> None:
    state = read_job_state()
    if not state:
        return
    meta = load_meta()
    job_id = str(state.get("jobId") or "")
    if not job_id or job_id == str(meta.get("last_synced_job_id") or ""):
        return
    if str(state.get("status") or "") not in {"done", "error"}:
        return
    history = load_jsonl(HISTORY_PATH)
    history.append(
        {
            "role": "agent",
            "text": pretty_print_job_result(state),
            "timestamp": float(state.get("updated_at") or time.time()),
            "job_id": job_id,
        }
    )
    HISTORY_PATH.write_text("\n".join(json.dumps(item, ensure_ascii=False) for item in history) + ("\n" if history else ""), encoding="utf-8")
    meta["last_synced_job_id"] = job_id
    save_meta(meta)


def get_state_payload() -> dict[str, Any]:
    sync_assistant_messages()
    sync_job_messages()
    job_status = read_job_state()
    status = {
        "status": str(job_status.get("status") or "idle"),
        "command": str(job_status.get("prompt") or ""),
        "summary": str(job_status.get("summary") or ""),
        "updated_at": float(job_status.get("updated_at") or time.time()),
    } if job_status else {"status": "idle", "command": "", "summary": "", "updated_at": time.time()}
    return {"status": status, "messages": load_jsonl(HISTORY_PATH)}


class Handler(BaseHTTPRequestHandler):
    def _send_json(self, payload: dict[str, Any], status: int = HTTPStatus.OK) -> None:
        raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def _send_html(self, raw: str) -> None:
        data = raw.encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/":
            self._send_html(HTML)
            return
        if parsed.path == "/api/state":
            self._send_json(get_state_payload())
            return
        self.send_error(HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        length = int(self.headers.get("Content-Length", "0") or "0")
        raw_body = self.rfile.read(length) if length else b"{}"
        try:
            payload = json.loads(raw_body.decode("utf-8"))
        except json.JSONDecodeError:
            payload = {}

        if parsed.path == "/api/message":
            text = str(payload.get("text") or "").strip()
            if not text:
                self._send_json({"ok": False, "error": "empty text"}, HTTPStatus.BAD_REQUEST)
                return
            append_jsonl(HISTORY_PATH, {"role": "user", "text": text, "timestamp": time.time()})
            project_response = handle_project_command(text)
            if project_response is not None:
                append_jsonl(HISTORY_PATH, {"role": "agent", "text": project_response, "timestamp": time.time()})
                self._send_json({"ok": True, "mode": "project_control"})
                return
            if should_route_to_operator(text):
                state = run_orchestrator_once(text)
                append_jsonl(
                    HISTORY_PATH,
                    {
                        "role": "agent",
                        "text": f"작업을 실행 모드로 넘겼습니다.\n- 상태: {state.get('status', '')}\n- 요약: {state.get('summary', '')}",
                        "timestamp": time.time(),
                    },
                )
                self._send_json({"ok": True, "mode": "operator"})
                return

            answer = call_fast_chat(text)
            append_jsonl(HISTORY_PATH, {"role": "agent", "text": answer, "timestamp": time.time()})
            self._send_json({"ok": True, "mode": "chat"})
            return

        if parsed.path == "/api/clear":
            HISTORY_PATH.write_text("", encoding="utf-8")
            save_meta({})
            self._send_json({"ok": True})
            return

        self.send_error(HTTPStatus.NOT_FOUND)

    def log_message(self, format: str, *args) -> None:
        return


def main() -> None:
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print(json.dumps({"chatUrl": f"http://{HOST}:{PORT}"}, ensure_ascii=False))
    server.serve_forever()


if __name__ == "__main__":
    main()
