from __future__ import annotations

import os
import time
from typing import Any
from urllib.parse import urlparse

from ..models import AgentJob, JobStep
from .openai_common import safe_text_response


RESEARCH_MODEL = os.environ.get("AGENT_RESEARCH_MODEL", "gpt-5.4-mini")
RESEARCH_REASONING_EFFORT = os.environ.get("AGENT_RESEARCH_REASONING_EFFORT", "low")

HIGH_TRUST_DOMAINS = (
    "docs.python.org",
    "platform.openai.com",
    "openai.com",
    "developer.mozilla.org",
    "developer.chrome.com",
    "learn.microsoft.com",
    "docs.github.com",
    "github.com",
    "pypi.org",
)


def build_source_cards(browser_context: dict[str, Any]) -> list[dict[str, str]]:
    cards: list[dict[str, str]] = []

    for item in browser_context.get("top_results") or []:
        if not isinstance(item, dict):
            continue
        url = str(item.get("url") or "").strip()
        if not url:
            continue
        parsed = urlparse(url)
        cards.append(
            {
                "title": str(item.get("title") or parsed.netloc or url)[:160],
                "url": url[:500],
                "domain": parsed.netloc[:120],
            }
        )

    for key in ("sources", "url", "search_url"):
        raw_values = browser_context.get(key) or []
        values = raw_values if isinstance(raw_values, list) else [raw_values]
        for raw in values:
            url = str(raw or "").strip()
            if not url or any(card["url"] == url for card in cards):
                continue
            parsed = urlparse(url)
            cards.append(
                {
                    "title": parsed.netloc or url,
                    "url": url[:500],
                    "domain": parsed.netloc[:120],
                }
            )

    return cards[:8]


def score_source_card(card: dict[str, str]) -> int:
    domain = str(card.get("domain") or "").lower()
    url = str(card.get("url") or "").lower()
    score = 0
    if any(domain == item or domain.endswith(f".{item}") for item in HIGH_TRUST_DOMAINS):
        score += 5
    if domain.endswith(".org"):
        score += 2
    if domain.endswith(".gov"):
        score += 3
    if domain.endswith(".edu"):
        score += 3
    if "docs" in domain or "/docs" in url:
        score += 2
    if url.startswith("https://"):
        score += 1
    if "search?" in url:
        score -= 2
    return score


def rank_source_cards(source_cards: list[dict[str, str]]) -> list[dict[str, str]]:
    ranked: list[dict[str, str]] = []
    for item in source_cards:
        ranked.append({**item, "score": str(score_source_card(item))})
    ranked.sort(
        key=lambda item: (
            int(item.get("score") or 0),
            len(str(item.get("title") or "")),
        ),
        reverse=True,
    )
    return ranked[:8]


def summarize_sources(source_cards: list[dict[str, str]]) -> list[str]:
    lines: list[str] = []
    for item in source_cards[:5]:
        title = str(item.get("title") or item.get("domain") or item.get("url") or "").strip()
        domain = str(item.get("domain") or "").strip()
        url = str(item.get("url") or "").strip()
        score = str(item.get("score") or "").strip()
        parts = [title]
        if domain and domain != title:
            parts.append(f"({domain})")
        if score:
            parts.append(f"[score {score}]")
        if url:
            parts.append(f"- {url}")
        lines.append(" ".join(parts).strip())
    return lines


def summarize_browser_context(browser_context: dict[str, Any]) -> dict[str, Any]:
    if not browser_context:
        return {}
    source_cards = rank_source_cards(build_source_cards(browser_context))
    return {
        "query": str(browser_context.get("query") or ""),
        "url": str(browser_context.get("url") or ""),
        "search_url": str(browser_context.get("search_url") or ""),
        "mode": str(browser_context.get("mode") or ""),
        "excerpt": str(browser_context.get("excerpt") or "")[:1200],
        "content_preview": str(browser_context.get("content_preview") or "")[:1800],
        "top_results": (browser_context.get("top_results") or [])[:5],
        "answer_blocks": (browser_context.get("answer_blocks") or [])[:3],
        "content_blocks": (browser_context.get("content_blocks") or [])[:5],
        "sources": [str(item) for item in browser_context.get("sources") or []][:8],
        "source_cards": source_cards,
        "source_summary": summarize_sources(source_cards),
    }


def build_browser_notes(browser_context: dict[str, Any]) -> list[str]:
    notes: list[str] = []
    preview = str(browser_context.get("content_preview") or "").strip()
    excerpt = str(browser_context.get("excerpt") or "").strip()
    if preview:
        notes.append("본문 미리보기")
        notes.append(preview[:600])
    elif excerpt:
        notes.append("본문 발췌")
        notes.append(excerpt[:600])
    for block in (browser_context.get("content_blocks") or [])[:3]:
        text = str((block or {}).get("text") or "").strip()
        if text:
            notes.append(text[:300])
    return notes[:5]


def build_fallback_report(job: AgentJob) -> dict[str, Any]:
    interpretation = job.metadata.get("interpretation") or {}
    plan = job.metadata.get("plan") or {}
    queries = interpretation.get("search_queries") or []
    focus = plan.get("research_focus") or interpretation.get("mvp_scope") or []
    browser_context = summarize_browser_context(job.metadata.get("browser_context") or {})
    implementation_notes = [
        "먼저 MVP 범위를 좁게 잡고 실행 가능한 첫 결과물을 만듭니다.",
        "외부 API나 데이터 소스가 필요하면 연결 방식과 샘플 응답 구조를 먼저 정리합니다.",
        "테스트 가능한 입력/출력 경로를 하나 이상 확보합니다.",
    ]
    browser_notes = build_browser_notes(browser_context)
    if browser_notes:
        implementation_notes.append("브라우저 본문에서 확인한 핵심 내용을 구현 메모에 반영합니다.")
    if browser_context.get("source_summary"):
        implementation_notes.append("출처 요약을 기준으로 우선순위 높은 참고 문서를 선택합니다.")

    sources: list[str] = []
    if browser_context:
        sources.extend(browser_context.get("sources") or [])
        if browser_context.get("url"):
            sources.insert(0, browser_context["url"])

    summary_parts = [
        f"'{interpretation.get('goal_summary') or job.prompt[:80]}' 요청에 대한 구현 전 조사 초안을 만들었습니다.",
    ]
    if browser_notes:
        summary_parts.append("브라우저 본문 핵심:")
        summary_parts.extend(browser_notes[:3])

    return {
        "mode": "heuristic",
        "summary": "\n".join(summary_parts).strip(),
        "queries": queries,
        "focus": focus,
        "implementation_notes": implementation_notes,
        "browser_context": browser_context,
        "browser_notes": browser_notes,
        "sources": list(dict.fromkeys(sources))[:8],
        "source_cards": browser_context.get("source_cards") or [],
        "source_summary": browser_context.get("source_summary") or [],
    }


def run_research(job: AgentJob) -> dict[str, Any]:
    interpretation = job.metadata.get("interpretation") or {}
    plan = job.metadata.get("plan") or {}
    memory_summary = str(job.metadata.get("memory_summary") or "")
    browser_context = summarize_browser_context(job.metadata.get("browser_context") or {})
    fallback = build_fallback_report(job)
    text = safe_text_response(
        developer_text=(
            "You are a research worker inside a local app-building agent system. "
            "Return a concise Korean report with sections: summary, key findings, implementation notes, risks, sources. "
            "If browser_context is provided, directly use content_preview, excerpt, content_blocks, and source_summary. "
            "Prefer short actionable guidance over long explanations."
        ),
        user_payload={
            "prompt": job.prompt,
            "interpretation": interpretation,
            "plan": plan,
            "memory_summary": memory_summary,
            "browser_context": browser_context,
            "fallback": fallback,
        },
        model=RESEARCH_MODEL,
        reasoning_effort=RESEARCH_REASONING_EFFORT,
        tools=[{"type": "web_search"}],
    )

    sources: list[str] = []
    if browser_context.get("url"):
        sources.append(browser_context["url"])
    sources.extend(browser_context.get("sources") or [])

    if not text:
        return fallback

    return {
        "mode": "openai",
        "summary": text,
        "queries": interpretation.get("search_queries") or [],
        "focus": plan.get("research_focus") or [],
        "implementation_notes": fallback.get("implementation_notes") or [],
        "browser_context": browser_context,
        "browser_notes": fallback.get("browser_notes") or [],
        "sources": list(dict.fromkeys([str(item) for item in sources]))[:8],
        "source_cards": browser_context.get("source_cards") or [],
        "source_summary": browser_context.get("source_summary") or [],
    }


class ResearchWorker:
    name = "research_worker"

    def can_handle(self, job: AgentJob) -> bool:
        return job.category == "research"

    def process(self, job: AgentJob) -> AgentJob:
        job.assigned_worker = self.name
        job.stage = "research"
        job.status = "running"
        job.steps = [
            JobStep(name="requirements_scan", status="done", note="요청과 프로젝트 메모리를 확인했습니다."),
            JobStep(name="source_collection", status="running", note="출처와 본문 핵심을 수집하고 있습니다."),
            JobStep(name="research_summary", status="pending", note="구현과 바로 연결되는 조사 결과를 정리합니다."),
        ]
        job.summary = "연구 작업이 구현 전 조사 보고서를 준비하고 있습니다."

        try:
            report = run_research(job)
            job.result = report
            job.status = "done"
            job.summary = "조사 결과를 정리했습니다."
            job.steps[1].status = "done"
            job.steps[1].note = "출처와 브라우저 본문 수집을 마쳤습니다."
            job.steps[1].updated_at = time.time()
            job.steps[2].status = "done"
            job.steps[2].note = "구현에 사용할 조사 보고서를 저장했습니다."
            job.steps[2].updated_at = time.time()
        except Exception as exc:
            fallback = build_fallback_report(job)
            fallback["error"] = str(exc)
            job.result = fallback
            job.status = "error"
            job.summary = f"조사 단계에서 오류가 발생했습니다: {exc}"
            job.steps[1].status = "error"
            job.steps[1].note = str(exc)
            job.steps[1].updated_at = time.time()

        return job
