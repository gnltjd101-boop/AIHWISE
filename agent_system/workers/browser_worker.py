from __future__ import annotations

import json
import os
from pathlib import Path
import time
from urllib.parse import quote_plus
from typing import Any

from ..models import AgentJob, JobStep
from ..paths import OUTPUT_DIR
from .openai_common import safe_json_response

try:
    from playwright.sync_api import sync_playwright
except Exception:  # pragma: no cover
    sync_playwright = None


BROWSER_MODEL = os.environ.get("AGENT_BROWSER_MODEL", "gpt-5.4-mini")
BROWSER_REASONING_EFFORT = os.environ.get("AGENT_BROWSER_REASONING_EFFORT", "low")
SEARCH_SELECTORS = [
    "textarea[name='q']",
    "input[name='q']",
    "input[type='search']",
    "#sb_form_q",
    "#searchbox input",
    "form[role='search'] input",
]
RESULT_SELECTORS = [
    ".b_ans",
    ".b_focusTextLarge",
    ".knowledge-panel",
    "#b_results",
    "#search",
    "main",
    "[role='main']",
    "body",
]


def fallback_browser_plan(prompt: str) -> dict[str, Any]:
    return {
        "url": "https://www.bing.com",
        "query": prompt.strip()[:120],
        "goal": prompt.strip()[:160],
    }


def build_browser_plan(prompt: str, interpretation: dict[str, Any] | None = None) -> dict[str, Any]:
    response = safe_json_response(
        developer_text=(
            "You are a browser automation planner. "
            "Return JSON only with keys: url, query, goal. "
            "Use a direct site URL when clear, otherwise use https://www.bing.com. "
            "Keep query short and practical."
        ),
        user_payload={"prompt": prompt, "interpretation": interpretation or {}},
        model=BROWSER_MODEL,
        reasoning_effort=BROWSER_REASONING_EFFORT,
    )
    return response or fallback_browser_plan(prompt)


def run_browser_task(job_id: str, plan: dict[str, Any]) -> dict[str, Any]:
    if sync_playwright is None:
        return {
            "goal": str(plan.get("goal") or ""),
            "title": "",
            "url": str(plan.get("url") or "https://www.bing.com"),
            "screenshot": "",
            "query": str(plan.get("query") or ""),
            "extracted_from": "",
            "answer_blocks": [],
            "excerpt": "Playwright가 설치되지 않아 브라우저 자동 실행은 생략했습니다.",
            "mode": "fallback",
        }

    output_dir = OUTPUT_DIR / job_id
    output_dir.mkdir(parents=True, exist_ok=True)
    screenshot_path = output_dir / "browser_result.png"

    start_url = str(plan.get("url") or "https://www.bing.com")
    query = str(plan.get("query") or "").strip()
    direct_search_url = start_url
    if query:
        lower_url = start_url.lower()
        if "bing.com" in lower_url:
            direct_search_url = f"https://www.bing.com/search?q={quote_plus(query)}"
        elif "google." in lower_url:
            direct_search_url = f"https://www.google.com/search?q={quote_plus(query)}"
        elif "naver.com" in lower_url:
            direct_search_url = f"https://search.naver.com/search.naver?query={quote_plus(query)}"

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto(direct_search_url, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(1200)

        if query and direct_search_url == start_url:
            locator = None
            for selector in SEARCH_SELECTORS:
                candidate = page.locator(selector).first
                if candidate.count():
                    locator = candidate
                    break
            if locator is not None:
                locator.fill(query)
                locator.press("Enter")
                page.wait_for_load_state("domcontentloaded", timeout=60000)
                page.wait_for_timeout(2200)

        page.screenshot(path=str(screenshot_path), full_page=True)
        title = page.title()
        final_url = page.url
        text = ""
        extracted_from = "body"
        answer_blocks: list[dict[str, str]] = []
        for selector in RESULT_SELECTORS:
            candidate = page.locator(selector).first
            if candidate.count():
                try:
                    candidate_text = candidate.inner_text(timeout=5000).strip()
                    if candidate_text:
                        answer_blocks.append({"selector": selector, "text": candidate_text[:1200]})
                        if not text:
                            text = candidate_text
                            extracted_from = selector
                        if selector not in {"#b_results", "#search", "main", "[role='main']", "body"}:
                            break
                except Exception:
                    continue
        browser.close()

    return {
        "goal": str(plan.get("goal") or ""),
        "title": title,
        "url": final_url,
        "screenshot": str(screenshot_path),
        "query": query,
        "extracted_from": extracted_from,
        "answer_blocks": answer_blocks[:5],
        "excerpt": text[:2500],
        "mode": "playwright",
    }


class BrowserWorker:
    name = "browser_worker"

    def can_handle(self, job: AgentJob) -> bool:
        return job.category == "browser"

    def process(self, job: AgentJob) -> AgentJob:
        job.assigned_worker = self.name
        job.stage = "browser"
        job.status = "running"
        job.steps = [
            JobStep(name="browser_plan", status="running", note="브라우저 자동화 계획을 만들고 있습니다."),
            JobStep(name="dom_execution", status="pending", note="브라우저 탐색 또는 폴백 실행을 수행합니다."),
            JobStep(name="capture_result", status="pending", note="검색 결과와 캡처를 정리합니다."),
        ]
        job.summary = "브라우저 작업이 검색과 추출을 준비하고 있습니다."

        try:
            interpretation = job.metadata.get("interpretation") or {}
            plan = build_browser_plan(job.prompt, interpretation)
            job.steps[0].status = "done"
            job.steps[0].note = f"시작 URL: {plan.get('url', '')}, 검색어: {plan.get('query', '')}"
            job.steps[0].updated_at = time.time()

            job.steps[1].status = "running"
            result = run_browser_task(job.id, plan)
            job.steps[1].status = "done"
            job.steps[1].note = f"브라우저 모드: {result.get('mode', '')}"
            job.steps[1].updated_at = time.time()

            job.steps[2].status = "done"
            job.steps[2].note = "브라우저 결과를 저장했습니다."
            job.steps[2].updated_at = time.time()

            job.status = "done"
            job.summary = "브라우저 작업을 완료했습니다."
            job.result = result
        except Exception as exc:
            job.status = "error"
            job.summary = f"브라우저 작업 중 오류가 발생했습니다: {exc}"
            job.result = {"error": str(exc)}
            for step in job.steps:
                if step.status == "running":
                    step.status = "error"
                    step.note = str(exc)
                    step.updated_at = time.time()
                    break

        return job
