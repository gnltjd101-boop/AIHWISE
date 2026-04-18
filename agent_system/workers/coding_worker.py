from __future__ import annotations

import json
import os
import re
import textwrap
import time
from pathlib import Path
from typing import Any

from ..models import AgentJob, JobStep
from ..paths import OUTPUT_DIR
from .openai_common import safe_json_response
from .test_worker import run_checks


CODING_MODEL = os.environ.get("AGENT_CODING_MODEL", "gpt-5.4-mini")
CODING_REASONING_EFFORT = os.environ.get("AGENT_CODING_REASONING_EFFORT", "medium")
TARGET_DIR_MARKER = "TARGET_OUTPUT_DIR:"


def extract_target_output_dir(job: AgentJob) -> Path:
    metadata_target = str(job.metadata.get("target_output_dir") or "").strip()
    if metadata_target:
        return Path(metadata_target)
    for line in job.prompt.splitlines():
        if line.strip().startswith(TARGET_DIR_MARKER):
            raw = line.split(TARGET_DIR_MARKER, 1)[1].strip()
            if raw:
                return Path(raw)
    return OUTPUT_DIR / job.project_id


def collect_existing_files(base_dir: Path) -> list[dict[str, str]]:
    items: list[dict[str, str]] = []
    if not base_dir.exists():
        return items
    for path in base_dir.rglob("*"):
        if not path.is_file():
            continue
        if "__pycache__" in path.parts or "_upgrades" in path.parts:
            continue
        try:
            content = path.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        try:
            relative = str(path.relative_to(base_dir)).replace(os.sep, "/")
        except ValueError:
            relative = path.name
        items.append({"path": relative, "content": content[:12000]})
        if len(items) >= 50:
            break
    return items


def tokenize_prompt(prompt: str) -> list[str]:
    return [token for token in re.split(r"[^0-9a-zA-Z가-힣_/-]+", prompt.lower()) if len(token) >= 2]


def select_relevant_existing_files(prompt: str, existing_files: list[dict[str, str]], limit: int = 12) -> list[dict[str, str]]:
    if not existing_files:
        return []
    prompt_tokens = tokenize_prompt(prompt)
    scored: list[tuple[int, dict[str, str]]] = []
    for file_info in existing_files:
        score = 0
        path = file_info["path"].lower()
        content = file_info["content"].lower()
        for token in prompt_tokens:
            if token in path:
                score += 4
            if token in content:
                score += 1
        if path.endswith(("package.json", "main.py", "app.py", "server.py", "index.html", "app.js")):
            score += 2
        scored.append((score, file_info))
    scored.sort(key=lambda item: (-item[0], item[1]["path"]))
    selected = [item[1] for item in scored[:limit] if item[0] > 0]
    return selected or [item[1] for item in scored[: min(limit, len(scored))]]


def detect_changed_files(base_dir: Path, existing_files: list[dict[str, str]], plan: dict[str, Any]) -> list[str]:
    existing_map = {item["path"]: item["content"] for item in existing_files}
    changed: list[str] = []
    for item in plan.get("files") or []:
        relative = str(item.get("path") or "").strip().replace("\\", "/")
        if not relative:
            continue
        new_content = str(item.get("content") or "")
        if existing_map.get(relative) != new_content:
            changed.append(str(base_dir / relative.replace("/", os.sep)))
    return changed


def write_output_files(base_dir: Path, plan: dict[str, Any]) -> list[str]:
    base_dir.mkdir(parents=True, exist_ok=True)
    written: list[str] = []
    for item in plan.get("files") or []:
        relative = str(item.get("path") or "").strip().replace("/", os.sep)
        if not relative:
            continue
        target = base_dir / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(str(item.get("content") or ""), encoding="utf-8")
        written.append(str(target))
    return written


def choose_fallback_mode(prompt: str, domain_mode: str) -> str:
    lowered = prompt.lower()
    if domain_mode in {"app_mode", "dashboard_mode"}:
        return "static_web"
    if domain_mode == "finance_mode" and any(token in lowered for token in ("dashboard", "ui", "web", "대시보드")):
        return "static_web"
    if any(token in lowered for token in ("앱", "web", "dashboard", "ui", "페이지", "브라우저")):
        return "static_web"
    return "python_cli"


def get_upgrade_candidate(job: AgentJob) -> str:
    return str(job.metadata.get("upgrade_candidate") or "").strip()


def should_enforce_multi_file_structure(interpretation: dict[str, Any]) -> bool:
    disliked = [str(item).strip().lower() for item in interpretation.get("disliked_patterns") or []]
    return any("파일 하나" in item or "one file" in item for item in disliked)


def plan_breaks_structure_feedback(plan: dict[str, Any], interpretation: dict[str, Any]) -> bool:
    if not should_enforce_multi_file_structure(interpretation):
        return False
    file_paths = [
        str(item.get("path") or "").strip().lower()
        for item in plan.get("files") or []
        if str(item.get("path") or "").strip()
    ]
    code_like = [path for path in file_paths if path.endswith((".py", ".js", ".html", ".css"))]
    return len(code_like) < 2


def build_static_web_plan(job: AgentJob, target_dir: Path) -> dict[str, Any]:
    interpretation = job.metadata.get("interpretation") or {}
    domain_mode = str(interpretation.get("domain_mode") or "general_mode")
    title = str(interpretation.get("project_title") or "Local AI Project")
    goal = str(interpretation.get("goal_summary") or job.prompt)
    requirements = [str(item) for item in interpretation.get("confirmed_requirements") or []][:6]
    scope = [str(item) for item in interpretation.get("mvp_scope") or []][:4]
    project_spec = {
        "title": title,
        "goal": goal,
        "domain_mode": domain_mode,
        "requirements": requirements,
        "scope": scope,
    }

    upgrade_candidate = get_upgrade_candidate(job)
    upgrade_features: list[str] = []
    upgrade_bonus = 0
    workflow_html = ""
    extra_file_entries: list[dict[str, Any]] = []

    if upgrade_candidate == "ui_improvement":
        workflow_html = """
      <article class="panel wide">
        <h2>권장 작업 흐름</h2>
        <ol class="flow">
          <li>요구사항을 정리한다.</li>
          <li>MVP 범위를 확인한다.</li>
          <li>실행 결과와 검증 로그를 확인한다.</li>
          <li>다음 개선 항목을 이어서 반영한다.</li>
        </ol>
      </article>
"""
        upgrade_features = ["workflow_section", "stronger_visual_hierarchy", "status_cards"]
        upgrade_bonus = 6
    elif upgrade_candidate == "performance_improvement":
        upgrade_features = ["lean_rendering", "smaller_markup"]
        upgrade_bonus = 3
    elif upgrade_candidate == "test_hardening":
        extra_file_entries.append(
            {
                "path": "smoke_test.py",
                "purpose": "기본 스모크 테스트",
                "content": (
                    "import json\n"
                    "from pathlib import Path\n\n"
                    "root = Path(__file__).resolve().parent\n"
                    "html = (root / 'index.html').read_text(encoding='utf-8')\n"
                    "spec = json.loads((root / 'project_spec.json').read_text(encoding='utf-8'))\n"
                    "assert '<main class=\"page\">' in html\n"
                    "assert spec.get('title')\n"
                    "assert spec.get('goal')\n"
                    "print('smoke ok')\n"
                ),
            }
        )
        upgrade_features = ["smoke_test", "spec_validation"]
        upgrade_bonus = 8
    elif upgrade_candidate == "code_cleanup":
        extra_file_entries.append(
            {
                "path": "docs/ARCHITECTURE.md",
                "purpose": "구조 설명 문서",
                "content": "# Architecture\n\n- index.html: UI shell\n- styles.css: layout and theme\n- app.js: client rendering\n- project_spec.json: structured project summary\n",
            }
        )
        upgrade_features = ["architecture_doc", "clearer_file_roles"]
        upgrade_bonus = 4

    html = f"""<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{title}</title>
  <link rel="stylesheet" href="styles.css">
</head>
<body>
  <main class="page">
    <section class="hero">
      <p class="eyebrow">Local AI Agent MVP</p>
      <h1>{title}</h1>
      <p class="lead">{goal}</p>
    </section>
    <section class="grid">
      <article class="panel">
        <h2>확정 요구사항</h2>
        <ul id="requirements"></ul>
      </article>
      <article class="panel">
        <h2>MVP 범위</h2>
        <ul id="scope"></ul>
      </article>
      <article class="panel wide">
        <h2>현재 상태</h2>
        <div id="statusCards" class="cards"></div>
      </article>
{workflow_html}
    </section>
  </main>
  <script src="app.js"></script>
</body>
</html>
"""
    css = """body {
  margin: 0;
  font-family: "Malgun Gothic", sans-serif;
  background: linear-gradient(180deg, #f5f0e8 0%, #fbf8f2 100%);
  color: #1f1a17;
}
.page {
  max-width: 1100px;
  margin: 0 auto;
  padding: 32px 20px 64px;
}
.hero {
  background: #fffaf2;
  border: 1px solid #dccdb8;
  border-radius: 24px;
  padding: 28px;
  box-shadow: 0 16px 42px rgba(49, 36, 21, 0.08);
}
.eyebrow {
  margin: 0 0 8px;
  text-transform: uppercase;
  letter-spacing: 0.14em;
  color: #7d5a29;
  font-size: 12px;
}
.lead {
  color: #584d43;
  max-width: 760px;
}
.grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
  gap: 18px;
  margin-top: 18px;
}
.panel {
  background: rgba(255, 252, 246, 0.94);
  border: 1px solid #dccdb8;
  border-radius: 20px;
  padding: 20px;
}
.wide {
  grid-column: 1 / -1;
}
.cards {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
  gap: 12px;
}
.card {
  border-radius: 16px;
  padding: 14px;
  background: #f1e6d5;
}
.flow {
  margin: 0;
  padding-left: 20px;
  line-height: 1.8;
}
ul {
  margin: 0;
  padding-left: 18px;
}
"""
    js = f"""const spec = {json.dumps(project_spec, ensure_ascii=False, indent=2)};

function renderList(id, items) {{
  const target = document.getElementById(id);
  target.innerHTML = "";
  for (const item of items) {{
    const li = document.createElement("li");
    li.textContent = item;
    target.appendChild(li);
  }}
}}

function renderCards() {{
  const cards = [
    ["도메인", spec.domain_mode],
    ["요구사항 수", String(spec.requirements.length)],
    ["MVP 범위", spec.scope.join(", ") || "기본 MVP"],
    ["프로젝트 목표", spec.goal],
  ];
  const target = document.getElementById("statusCards");
  target.innerHTML = "";
  for (const [label, value] of cards) {{
    const el = document.createElement("article");
    el.className = "card";
    el.innerHTML = `<strong>${{label}}</strong><div>${{value}}</div>`;
    target.appendChild(el);
  }}
}}

renderList("requirements", spec.requirements.length ? spec.requirements : ["요구사항을 정리하면 여기에 누적됩니다."]);
renderList("scope", spec.scope.length ? spec.scope : ["실행 가능한 MVP", "기본 데이터 구조", "다음 개선 여지"]);
renderCards();
"""
    main_py = textwrap.dedent(
        f"""
        import argparse
        import http.server
        import socketserver


        def main() -> int:
            parser = argparse.ArgumentParser(description="{goal}")
            parser.add_argument("--serve", action="store_true", help="정적 웹 결과물을 로컬 서버로 실행합니다.")
            parser.add_argument("--port", type=int, default=8000, help="실행 포트")
            args = parser.parse_args()
            if not args.serve:
                print("정적 웹 결과물입니다. --serve 옵션으로 확인할 수 있습니다.")
                return 0
            handler = http.server.SimpleHTTPRequestHandler
            with socketserver.TCPServer(("127.0.0.1", args.port), handler) as httpd:
                print(f"http://127.0.0.1:{{args.port}}")
                httpd.serve_forever()
            return 0


        if __name__ == "__main__":
            raise SystemExit(main())
        """
    ).strip() + "\n"
    readme = f"""# {title}

이 결과물은 로컬 AI 에이전트의 자동 빌드 결과입니다.

## 목표
- {goal}

## 현재 구성
- 정적 웹 MVP
- 요구사항/범위 표시 UI
- 이후 개선을 위한 구조화된 프로젝트 스펙 파일

## 실행
```powershell
python -m http.server 8000
```
"""
    return {
        "goal_summary": goal,
        "app_type": "static_web_mvp",
        "stack": "HTML/CSS/JavaScript",
        "files": [
            {"path": "index.html", "purpose": "메인 UI", "content": html},
            {"path": "styles.css", "purpose": "스타일", "content": css},
            {"path": "app.js", "purpose": "화면 렌더링", "content": js},
            {"path": "main.py", "purpose": "정적 웹 실행 엔트리포인트", "content": main_py},
            {"path": "project_spec.json", "purpose": "구조화된 프로젝트 사양", "content": json.dumps(project_spec, ensure_ascii=False, indent=2)},
            {"path": "README.md", "purpose": "실행 안내", "content": readme},
            *extra_file_entries,
        ],
        "upgrade_candidate": upgrade_candidate,
        "upgrade_features": upgrade_features,
        "upgrade_bonus": upgrade_bonus,
        "generated_by": "fallback",
    }


def build_python_cli_plan(job: AgentJob, target_dir: Path) -> dict[str, Any]:
    interpretation = job.metadata.get("interpretation") or {}
    title = str(interpretation.get("project_title") or "Local AI Tool")
    goal = str(interpretation.get("goal_summary") or job.prompt)
    requirements = [str(item) for item in interpretation.get("confirmed_requirements") or []][:6]
    scope = [str(item) for item in interpretation.get("mvp_scope") or []][:4]
    spec = {
        "title": title,
        "goal": goal,
        "domain_mode": interpretation.get("domain_mode") or "general_mode",
        "requirements": requirements,
        "scope": scope,
    }

    upgrade_candidate = get_upgrade_candidate(job)
    upgrade_features: list[str] = []
    upgrade_bonus = 0
    extra_files: list[dict[str, Any]] = []
    if upgrade_candidate == "test_hardening":
        extra_files.append(
            {
                "path": "smoke_test.py",
                "purpose": "CLI 스모크 테스트",
                "content": (
                    "import subprocess\n"
                    "completed = subprocess.run(['python', 'main.py', '--demo'], capture_output=True, text=True, check=True)\n"
                    "assert completed.returncode == 0\n"
                    "assert completed.stdout.strip()\n"
                    "print('smoke ok')\n"
                ),
            }
        )
        upgrade_features = ["cli_smoke_test"]
        upgrade_bonus = 8
    elif upgrade_candidate == "code_cleanup":
        extra_files.append(
            {
                "path": "docs/USAGE.md",
                "purpose": "CLI 사용 가이드",
                "content": "# Usage\n\n```powershell\npython .\\main.py --help\npython .\\main.py --demo\n```\n",
            }
        )
        upgrade_features = ["usage_doc"]
        upgrade_bonus = 4
    elif upgrade_candidate == "performance_improvement":
        upgrade_features = ["lean_cli_flow"]
        upgrade_bonus = 3
    elif upgrade_candidate == "ui_improvement":
        upgrade_features = ["clearer_cli_output"]
        upgrade_bonus = 2

    main_py = (
        "import argparse\n"
        "import json\n\n"
        f"PROJECT_SPEC = {json.dumps(spec, ensure_ascii=False, indent=2)}\n\n"
        "def build_parser() -> argparse.ArgumentParser:\n"
        "    parser = argparse.ArgumentParser(description=PROJECT_SPEC['goal'])\n"
        "    parser.add_argument('--show-spec', action='store_true', help='프로젝트 사양을 출력합니다.')\n"
        "    parser.add_argument('--demo', action='store_true', help='샘플 실행 결과를 출력합니다.')\n"
        "    return parser\n\n"
        "def main() -> int:\n"
        "    parser = build_parser()\n"
        "    args = parser.parse_args()\n"
        "    if args.show_spec:\n"
        "        print(json.dumps(PROJECT_SPEC, ensure_ascii=False, indent=2))\n"
        "        return 0\n"
        "    if args.demo:\n"
        "        print('샘플 실행 완료')\n"
        "        print('목표:', PROJECT_SPEC['goal'])\n"
        "        print('범위:', ', '.join(PROJECT_SPEC['scope']))\n"
        "        return 0\n"
        "    print(PROJECT_SPEC['title'])\n"
        "    print(PROJECT_SPEC['goal'])\n"
        "    print('실행 확인용 CLI 엔트리포인트가 준비되었습니다.')\n"
        "    print('옵션: --show-spec, --demo')\n"
        "    return 0\n\n"
        "if __name__ == '__main__':\n"
        "    raise SystemExit(main())\n"
    )
    readme = f"""# {title}

이 결과물은 로컬 AI 에이전트의 자동 CLI 빌드 결과입니다.

## 목표
- {goal}

## 실행
```powershell
python .\\main.py --help
python .\\main.py --demo
```
"""
    return {
        "goal_summary": goal,
        "app_type": "python_cli_mvp",
        "stack": "Python",
        "files": [
            {"path": "main.py", "purpose": "CLI 엔트리포인트", "content": main_py},
            {"path": "project_spec.json", "purpose": "구조화된 프로젝트 사양", "content": json.dumps(spec, ensure_ascii=False, indent=2)},
            {"path": "README.md", "purpose": "실행 안내", "content": readme},
            *extra_files,
        ],
        "upgrade_candidate": upgrade_candidate,
        "upgrade_features": upgrade_features,
        "upgrade_bonus": upgrade_bonus,
        "generated_by": "fallback",
    }


def build_fallback_plan(job: AgentJob, target_dir: Path) -> dict[str, Any]:
    interpretation = job.metadata.get("interpretation") or {}
    mode = choose_fallback_mode(job.prompt, str(interpretation.get("domain_mode") or "general_mode"))
    if mode == "static_web":
        return build_static_web_plan(job, target_dir)
    return build_python_cli_plan(job, target_dir)


def request_model_plan(job: AgentJob, existing_files: list[dict[str, str]]) -> dict[str, Any] | None:
    interpretation = job.metadata.get("interpretation") or {}
    plan = job.metadata.get("plan") or {}
    research = job.metadata.get("research") or {}
    response = safe_json_response(
        developer_text=(
            "You are a builder worker inside a local AI build agent. "
            "Return JSON only with keys: goal_summary, app_type, stack, files. "
            "files must be an array of objects with keys path, purpose, content. "
            "Prefer minimal runnable MVPs. "
            "Strongly prefer zero-dependency outputs using static HTML/CSS/JS or standard-library Python. "
            "Avoid Streamlit, FastAPI, Flask, React, Vite, npm, and third-party dependencies unless the user explicitly requested them. "
            "If disliked_patterns mention keeping everything in one file, split responsibilities across multiple files. "
            "If continuing an existing project, modify only needed files and keep the current structure."
        ),
        user_payload={
            "prompt": job.prompt,
            "interpretation": interpretation,
            "plan": plan,
            "research": research,
            "existing_files": existing_files,
            "upgrade_candidate": job.metadata.get("upgrade_candidate", ""),
        },
        model=CODING_MODEL,
        reasoning_effort=CODING_REASONING_EFFORT,
    )
    if not response or not isinstance(response.get("files"), list):
        return None
    return response


def plan_uses_external_dependencies(plan: dict[str, Any]) -> bool:
    dependency_tokens = ("streamlit", "fastapi", "flask", "django", "react", "vite", "plotly", "pandas", "npm", "package.json", "requirements.txt")
    for item in plan.get("files") or []:
        path = str(item.get("path") or "").lower()
        content = str(item.get("content") or "").lower()
        if any(token in path or token in content for token in dependency_tokens):
            return True
    stack = str(plan.get("stack") or "").lower()
    return any(token in stack for token in dependency_tokens)


def user_explicitly_requested_framework(prompt: str) -> bool:
    lowered = prompt.lower()
    return any(token in lowered for token in ("streamlit", "fastapi", "flask", "django", "react", "vite", "next.js", "vue"))


def request_model_repair(job: AgentJob, validation: dict[str, Any], existing_files: list[dict[str, str]]) -> dict[str, Any] | None:
    interpretation = job.metadata.get("interpretation") or {}
    response = safe_json_response(
        developer_text=(
            "You are a repair worker for a local AI build agent. "
            "Return JSON only with key files. "
            "files must contain only the files that need to change, each with path and content."
        ),
        user_payload={
            "prompt": job.prompt,
            "interpretation": interpretation,
            "validation": validation,
            "existing_files": existing_files,
        },
        model=CODING_MODEL,
        reasoning_effort="low",
    )
    if not response or not isinstance(response.get("files"), list):
        return None
    return response


class CodingWorker:
    name = "coding_worker"

    def can_handle(self, job: AgentJob) -> bool:
        return job.category == "coding"

    def process(self, job: AgentJob) -> AgentJob:
        job.assigned_worker = self.name
        job.stage = "build"
        job.status = "running"
        job.steps = [
            JobStep(name="project_scan", status="done", note="기존 프로젝트 구조와 출력 위치를 확인했습니다."),
            JobStep(name="implementation_plan", status="running", note="구현 계획을 만들고 있습니다."),
            JobStep(name="file_changes", status="pending", note="파일을 생성하거나 수정합니다."),
            JobStep(name="auto_repair", status="pending", note="기본 검증 실패 시 1회 자동 복구를 시도합니다."),
        ]
        job.summary = "빌더가 구현 계획을 준비하고 있습니다."

        try:
            target_dir = extract_target_output_dir(job)
            existing_files = collect_existing_files(target_dir)
            relevant_files = select_relevant_existing_files(job.prompt, existing_files)
            generated_by = "fallback"
            failure_analysis = job.metadata.get("failure_analysis") or {}
            force_fallback = bool(failure_analysis.get("failure_types")) and any(
                item in ("run_failed", "build_validation_failed") for item in failure_analysis.get("failure_types") or []
            )

            plan = None if force_fallback else request_model_plan(job, relevant_files if relevant_files else existing_files)
            if plan and plan_uses_external_dependencies(plan) and not user_explicitly_requested_framework(job.prompt):
                plan = None
            if plan and plan_breaks_structure_feedback(plan, interpretation):
                plan = None
            if not plan:
                plan = build_fallback_plan(job, target_dir)
            else:
                generated_by = "openai"

            changed_files = detect_changed_files(target_dir, existing_files, plan)
            written_files = write_output_files(target_dir, plan)
            validation = run_checks(target_dir, written_files)

            repair_summary: dict[str, Any] = {
                "attempted": False,
                "updated_files": [],
                "validation": validation,
            }

            if int(validation.get("failed", 0) or 0) > 0:
                job.steps[3].status = "running"
                current_files = collect_existing_files(target_dir)
                repair_plan = request_model_repair(job, validation, current_files)
                if repair_plan:
                    updated_files = write_output_files(target_dir, repair_plan)
                    validation = run_checks(target_dir, written_files)
                    for path in updated_files:
                        if path not in changed_files:
                            changed_files.append(path)
                    repair_summary = {
                        "attempted": True,
                        "updated_files": updated_files,
                        "validation": validation,
                    }
                job.steps[3].status = "done" if int(validation.get("failed", 0) or 0) == 0 else "error"
                job.steps[3].note = f"자동 복구 후 실패 수: {validation.get('failed', 0)}"
                job.steps[3].updated_at = time.time()
            else:
                job.steps[3].status = "done"
                job.steps[3].note = "자동 복구가 필요하지 않았습니다."
                job.steps[3].updated_at = time.time()

            job.result = {
                "goal_summary": plan.get("goal_summary", ""),
                "app_type": plan.get("app_type", ""),
                "stack": plan.get("stack", ""),
                "output_dir": str(target_dir),
                "written_files": written_files,
                "changed_files": changed_files,
                "continued_project": bool(existing_files),
                "existing_file_count": len(existing_files),
                "candidate_context_files": [item["path"] for item in relevant_files],
                "selected_context_files": [item["path"] for item in relevant_files],
                "validation": validation,
                "repair": repair_summary,
                "upgrade_candidate": plan.get("upgrade_candidate", ""),
                "upgrade_features": [str(item) for item in plan.get("upgrade_features") or []],
                "upgrade_bonus": int(plan.get("upgrade_bonus", 0) or 0),
                "confirmed_requirements": [str(item) for item in (job.metadata.get("interpretation") or {}).get("confirmed_requirements") or []][:8],
                "disliked_patterns": [str(item) for item in (job.metadata.get("interpretation") or {}).get("disliked_patterns") or []][:8],
                "next_priorities": [str(item) for item in (job.metadata.get("plan") or {}).get("next_priorities") or []][:8],
                "research_sources": [str(item) for item in (job.metadata.get("research") or {}).get("sources") or []][:8],
                "research_source_summary": [str(item) for item in (job.metadata.get("research") or {}).get("source_summary") or []][:8],
                "research_browser_notes": [str(item) for item in (job.metadata.get("research") or {}).get("browser_notes") or []][:8],
                "structure_feedback_enforced": should_enforce_multi_file_structure(job.metadata.get("interpretation") or {}),
                "generated_by": generated_by,
            }
            job.status = "done" if int(validation.get("failed", 0) or 0) == 0 else "error"
            job.summary = f"구현 완료. 기본 검증 통과 {validation.get('passed', 0)}건 / 실패 {validation.get('failed', 0)}건"
            job.steps[1].status = "done"
            job.steps[1].note = f"{plan.get('app_type', 'mvp')} 계획을 확정했습니다."
            job.steps[1].updated_at = time.time()
            job.steps[2].status = "done" if job.status == "done" else "error"
            job.steps[2].note = f"{len(written_files)}개 파일을 기록했고 {len(changed_files)}개 파일이 실제로 변경됐습니다."
            job.steps[2].updated_at = time.time()
        except Exception as exc:
            job.status = "error"
            job.summary = f"코딩 단계에서 오류가 발생했습니다: {exc}"
            job.result = {"error": str(exc)}
            for step in job.steps:
                if step.status == "running":
                    step.status = "error"
                    step.note = str(exc)
                    step.updated_at = time.time()
                    break

        return job
