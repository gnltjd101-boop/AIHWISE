from __future__ import annotations

import os
import re
import time
import getpass
from pathlib import Path
from typing import Any
from urllib.parse import quote_plus

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
RESULT_CONTAINER_SELECTORS = [
    "#b_results",
    "#search",
    "main",
    "[role='main']",
    "body",
]
ANSWER_BLOCK_SELECTORS = [
    ".b_ans",
    ".b_focusTextLarge",
    ".knowledge-panel",
    "[data-attrid='title']",
]
RESULT_LINK_SELECTORS = [
    "#b_results h2 a",
    "#search a h3",
    "main a",
]
DIRECT_URL_RE = re.compile(r"https?://[^\s]+", re.IGNORECASE)


def should_enable_playwright() -> bool:
    raw = os.environ.get("AGENT_ENABLE_PLAYWRIGHT", "").strip().lower()
    if raw in {"0", "false", "no", "off"}:
        return False
    if raw in {"1", "true", "yes", "on"}:
        return True
    if any(
        str(value).strip()
        for key, value in os.environ.items()
        if key.upper().startswith("CODEX_SANDBOX")
    ):
        return False
    username = (os.environ.get("USERNAME") or getpass.getuser() or "").strip().lower()
    if username.startswith("codexsandbox"):
        return False
    return True


def extract_direct_url(prompt: str) -> str:
    match = DIRECT_URL_RE.search(prompt)
    return match.group(0).rstrip(".,)") if match else ""


def fallback_browser_plan(prompt: str) -> dict[str, Any]:
    direct_url = extract_direct_url(prompt)
    if direct_url:
        return {
            "url": direct_url,
            "query": "",
            "goal": prompt.strip()[:160],
            "mode": "direct_url",
        }
    return {
        "url": "https://www.bing.com",
        "query": prompt.strip()[:120],
        "goal": prompt.strip()[:160],
        "mode": "search",
    }


def build_browser_plan(prompt: str, interpretation: dict[str, Any] | None = None) -> dict[str, Any]:
    response = safe_json_response(
        developer_text=(
            "You are a browser automation planner. "
            "Return JSON only with keys: url, query, goal, mode. "
            "mode must be one of direct_url or search. "
            "If a direct URL is present in the prompt, use it. "
            "Otherwise default to https://www.bing.com and provide a short practical query."
        ),
        user_payload={"prompt": prompt, "interpretation": interpretation or {}, "fallback": fallback_browser_plan(prompt)},
        model=BROWSER_MODEL,
        reasoning_effort=BROWSER_REASONING_EFFORT,
    )
    plan = response or fallback_browser_plan(prompt)
    plan["url"] = str(plan.get("url") or fallback_browser_plan(prompt)["url"])
    plan["query"] = str(plan.get("query") or "")
    plan["goal"] = str(plan.get("goal") or prompt.strip()[:160])
    plan["mode"] = str(plan.get("mode") or ("direct_url" if extract_direct_url(prompt) else "search"))
    return plan


def build_search_url(base_url: str, query: str) -> str:
    lower_url = base_url.lower()
    if "bing.com" in lower_url:
        return f"https://www.bing.com/search?q={quote_plus(query)}"
    if "google." in lower_url:
        return f"https://www.google.com/search?q={quote_plus(query)}"
    if "naver.com" in lower_url:
        return f"https://search.naver.com/search.naver?query={quote_plus(query)}"
    return base_url


def fallback_result(plan: dict[str, Any], reason: str) -> dict[str, Any]:
    query = str(plan.get("query") or "")
    url = str(plan.get("url") or "https://www.bing.com")
    if query and plan.get("mode") != "direct_url":
        url = build_search_url(url, query)
    return {
        "goal": str(plan.get("goal") or ""),
        "title": "",
        "url": url,
        "query": query,
        "mode": "fallback",
        "plan_mode": str(plan.get("mode") or "search"),
        "search_url": url,
        "screenshot": "",
        "extracted_from": "",
        "answer_blocks": [],
        "top_results": [],
        "excerpt": reason,
        "sources": [],
    }


def extract_answer_blocks(page) -> list[dict[str, str]]:
    blocks: list[dict[str, str]] = []
    for selector in ANSWER_BLOCK_SELECTORS:
        try:
            locators = page.locator(selector)
            count = min(locators.count(), 3)
            for index in range(count):
                text = locators.nth(index).inner_text(timeout=3000).strip()
                if text:
                    blocks.append({"selector": selector, "text": text[:1200]})
        except Exception:
            continue
    deduped: list[dict[str, str]] = []
    seen: set[str] = set()
    for block in blocks:
        text = block["text"]
        if text not in seen:
            seen.add(text)
            deduped.append(block)
    return deduped[:5]


def extract_top_results(page) -> list[dict[str, str]]:
    results: list[dict[str, str]] = []
    for selector in RESULT_LINK_SELECTORS:
        try:
            locators = page.locator(selector)
            count = min(locators.count(), 5)
            for index in range(count):
                item = locators.nth(index)
                title = item.inner_text(timeout=3000).strip()
                href = item.evaluate("(el) => el.closest('a') ? el.closest('a').href : el.href")
                if title and href:
                    results.append({"title": title[:200], "url": str(href)[:500]})
        except Exception:
            continue
        if results:
            break
    deduped: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in results:
        key = f"{item['title']}|{item['url']}"
        if key not in seen:
            seen.add(key)
            deduped.append(item)
    return deduped[:5]


def extract_main_excerpt(page) -> tuple[str, str]:
    for selector in RESULT_CONTAINER_SELECTORS:
        try:
            locator = page.locator(selector).first
            if locator.count():
                text = locator.inner_text(timeout=5000).strip()
                if text:
                    return selector, text[:2500]
        except Exception:
            continue
    return "", ""


def run_browser_task(job_id: str, plan: dict[str, Any]) -> dict[str, Any]:
    if not should_enable_playwright():
        return fallback_result(plan, "Playwright is disabled in this environment. Set AGENT_ENABLE_PLAYWRIGHT=1 to force browser automation.")
    if sync_playwright is None:
        return fallback_result(plan, "Playwright is not installed, so browser automation was skipped.")

    output_dir = OUTPUT_DIR / job_id
    output_dir.mkdir(parents=True, exist_ok=True)
    screenshot_path = output_dir / "browser_result.png"

    start_url = str(plan.get("url") or "https://www.bing.com")
    query = str(plan.get("query") or "").strip()
    search_url = start_url
    if query and str(plan.get("mode") or "search") != "direct_url":
        search_url = build_search_url(start_url, query)

    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(search_url, wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(1200)

            if query and search_url == start_url and str(plan.get("mode") or "search") != "direct_url":
                for selector in SEARCH_SELECTORS:
                    try:
                        candidate = page.locator(selector).first
                        if candidate.count():
                            candidate.fill(query)
                            candidate.press("Enter")
                            page.wait_for_load_state("domcontentloaded", timeout=60000)
                            page.wait_for_timeout(2200)
                            break
                    except Exception:
                        continue

            page.screenshot(path=str(screenshot_path), full_page=True)
            title = page.title()
            final_url = page.url
            extracted_from, excerpt = extract_main_excerpt(page)
            answer_blocks = extract_answer_blocks(page)
            top_results = extract_top_results(page)
            browser.close()
    except Exception as exc:
        return fallback_result(plan, f"Browser automation failed: {exc}")

    sources = []
    for item in top_results:
        sources.append(item["url"])

    return {
        "goal": str(plan.get("goal") or ""),
        "title": title,
        "url": final_url,
        "query": query,
        "mode": "playwright",
        "plan_mode": str(plan.get("mode") or "search"),
        "search_url": search_url,
        "screenshot": str(screenshot_path),
        "extracted_from": extracted_from,
        "answer_blocks": answer_blocks,
        "top_results": top_results,
        "excerpt": excerpt,
        "sources": sources,
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
            JobStep(name="dom_execution", status="pending", note="브라우저 검색 또는 직접 접속을 수행합니다."),
            JobStep(name="capture_result", status="pending", note="검색 결과와 캡처를 정리합니다."),
        ]
        job.summary = "브라우저 작업이 검색 결과 추출을 준비하고 있습니다."

        try:
            interpretation = job.metadata.get("interpretation") or {}
            plan = build_browser_plan(job.prompt, interpretation)
            job.steps[0].status = "done"
            job.steps[0].note = f"start={plan.get('url', '')} query={plan.get('query', '')}"
            job.steps[0].updated_at = time.time()

            job.steps[1].status = "running"
            result = run_browser_task(job.id, plan)
            job.steps[1].status = "done"
            job.steps[1].note = f"mode={result.get('mode', '')} results={len(result.get('top_results') or [])}"
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
