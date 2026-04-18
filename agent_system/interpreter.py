from __future__ import annotations

import json
import re
from typing import Any

from .workers.openai_common import safe_json_response


DOMAIN_KEYWORDS: dict[str, tuple[str, ...]] = {
    "finance_mode": ("업비트", "빗썸", "거래소", "차익", "시세", "백테스트", "전략", "투자", "코인", "주식", "finance", "trading"),
    "app_mode": ("앱", "모바일", "안드로이드", "ios", "네비", "내비", "서비스", "회원", "화면", "ui", "ux"),
    "automation_mode": ("자동화", "반복", "매크로", "봇", "스케줄", "예약", "파일 처리", "workflow", "automation"),
    "data_mode": ("크롤러", "수집", "정제", "etl", "파싱", "데이터", "csv", "json", "scrape", "crawl"),
    "dashboard_mode": ("대시보드", "시각화", "차트", "통계", "모니터링", "리포트", "dashboard"),
}

ROUTE_HINTS: dict[str, tuple[str, ...]] = {
    "browser": ("검색", "찾아", "브라우저", "웹에서", "사이트", "screenshot", "browser", "google", "naver", "bing"),
    "research": ("조사", "리서치", "문서", "정리", "비교", "분석"),
    "coding": ("만들", "구현", "개발", "코드", "수정", "앱", "툴", "대시보드", "크롤러", "자동화"),
}

OPERATOR_TRIGGERS = (
    "만들", "구현", "개발", "수정", "고쳐", "실행", "테스트", "검증", "빌드", "브라우저", "검색", "찾아",
    "crawler", "dashboard", "build", "test", "run", "browser", "research", "code", "app",
)

DOMAIN_PRIORITIES: dict[str, list[str]] = {
    "finance_mode": ["데이터 수집기", "전략 엔진", "백테스트/시뮬레이션", "리스크/성능 지표", "대시보드"],
    "app_mode": ["사용자 플로우", "화면 구조", "UI/UX", "실행 가능한 MVP", "개선 루프"],
    "automation_mode": ["입력/처리/출력 흐름", "반복 실행 구조", "로그", "에러 복구", "스케줄링"],
    "data_mode": ["수집기", "정제", "저장 구조", "예외 처리", "재실행 가능성"],
    "dashboard_mode": ["데이터 연결", "시각화", "필터링", "상태 표시", "오류 표시"],
    "general_mode": ["요구사항 정리", "실행 가능한 MVP", "테스트", "개선 루프"],
}


def _normalize_prompt(prompt: str) -> str:
    return re.sub(r"\s+", " ", prompt).strip()


def _contains_any(text: str, keywords: tuple[str, ...]) -> bool:
    lowered = text.lower()
    return any(keyword.lower() in lowered for keyword in keywords)


def detect_domain_mode(prompt: str) -> str:
    normalized = _normalize_prompt(prompt)
    scored: list[tuple[int, str]] = []
    for domain_mode, keywords in DOMAIN_KEYWORDS.items():
        score = sum(1 for keyword in keywords if keyword.lower() in normalized.lower())
        if score:
            scored.append((score, domain_mode))
    if not scored:
        return "general_mode"
    scored.sort(reverse=True)
    return scored[0][1]


def detect_route_category(prompt: str) -> str:
    normalized = _normalize_prompt(prompt)
    if _contains_any(normalized, ROUTE_HINTS["browser"]):
        if any(word in normalized.lower() for word in ("만들", "구현", "개발", "수정", "build", "code")):
            return "coding"
        return "browser"
    if _contains_any(normalized, ROUTE_HINTS["research"]):
        if any(word in normalized.lower() for word in ("만들", "구현", "개발", "수정", "build", "code")):
            return "coding"
        return "research"
    if _contains_any(normalized, ROUTE_HINTS["coding"]):
        return "coding"
    return "coding"


def extract_requirements(prompt: str) -> list[str]:
    normalized = prompt.replace("\r", "\n")
    lines = [line.strip(" -\t") for line in normalized.splitlines() if line.strip()]
    if len(lines) > 1:
        return lines[:8]
    chunks = [chunk.strip() for chunk in re.split(r"[,.]\s+|그리고\s+|및\s+", _normalize_prompt(prompt)) if chunk.strip()]
    return chunks[:8]


def build_search_queries(prompt: str, domain_mode: str) -> list[str]:
    base = _normalize_prompt(prompt)
    suffix_map = {
        "finance_mode": ["시장 구조", "API 문서", "백테스트 예제"],
        "app_mode": ["앱 UX 사례", "MVP 기능", "기술 스택"],
        "automation_mode": ["입출력 설계", "오류 복구", "로그 전략"],
        "data_mode": ["데이터 소스", "정제 전략", "저장 구조"],
        "dashboard_mode": ["대시보드 예제", "시각화 설계", "필터 구조"],
        "general_mode": ["MVP 구조", "기술 스택", "실행 방법"],
    }
    queries = [base]
    for suffix in suffix_map.get(domain_mode, suffix_map["general_mode"]):
        queries.append(f"{base} {suffix}")
    return queries[:4]


def heuristic_interpret(prompt: str, memory: dict[str, Any] | None = None) -> dict[str, Any]:
    memory = memory or {}
    domain_mode = detect_domain_mode(prompt)
    route_category = detect_route_category(prompt)
    requirements = extract_requirements(prompt)
    continuation = any(token in prompt for token in ("고도화", "개선", "이어", "수정", "계속", "다음"))
    goal_summary = requirements[0] if requirements else _normalize_prompt(prompt)
    disliked_patterns = [str(item) for item in memory.get("disliked_patterns") or []]
    confirmed_requirements = list(dict.fromkeys([*memory.get("confirmed_requirements", []), *requirements]))[:12]
    return {
        "route_category": route_category,
        "domain_mode": domain_mode,
        "goal_summary": goal_summary[:160],
        "project_title": goal_summary[:60],
        "continuation": continuation,
        "requires_browser": route_category == "browser",
        "requires_research": True,
        "requires_build": route_category == "coding",
        "requires_run": route_category == "coding",
        "requires_test": route_category == "coding",
        "requires_review": route_category == "coding",
        "confirmed_requirements": confirmed_requirements,
        "disliked_patterns": disliked_patterns,
        "search_queries": build_search_queries(prompt, domain_mode),
        "mvp_scope": DOMAIN_PRIORITIES.get(domain_mode, DOMAIN_PRIORITIES["general_mode"])[:3],
        "success_criteria": [
            "최소 1개 실행 가능한 결과물 생성",
            "기본 검증 단계 완료",
            "최근 실패 원인 또는 다음 개선 포인트 기록",
        ],
    }


def interpret_request(prompt: str, memory: dict[str, Any] | None = None) -> dict[str, Any]:
    base = heuristic_interpret(prompt, memory)
    response = safe_json_response(
        developer_text=(
            "You are a task interpreter for a local AI build agent. "
            "Return JSON only. Keys: route_category, domain_mode, goal_summary, project_title, "
            "continuation, requires_browser, requires_research, requires_build, requires_run, "
            "requires_test, requires_review, confirmed_requirements, disliked_patterns, search_queries, "
            "mvp_scope, success_criteria. "
            "route_category must be one of browser, research, coding. "
            "domain_mode must be one of finance_mode, app_mode, automation_mode, data_mode, dashboard_mode, general_mode."
        ),
        user_payload={"prompt": prompt, "memory": memory or {}, "heuristic": base},
        model="gpt-5.4-mini",
        reasoning_effort="low",
    )
    if not response:
        return base
    merged = dict(base)
    merged.update({key: value for key, value in response.items() if value not in (None, "", [], {})})
    merged["route_category"] = str(merged.get("route_category") or base["route_category"])
    merged["domain_mode"] = str(merged.get("domain_mode") or base["domain_mode"])
    merged["confirmed_requirements"] = [str(item) for item in merged.get("confirmed_requirements") or base["confirmed_requirements"]]
    merged["search_queries"] = [str(item) for item in merged.get("search_queries") or base["search_queries"]]
    merged["mvp_scope"] = [str(item) for item in merged.get("mvp_scope") or base["mvp_scope"]]
    merged["success_criteria"] = [str(item) for item in merged.get("success_criteria") or base["success_criteria"]]
    return merged


def should_route_to_operator(prompt: str) -> bool:
    lowered = prompt.lower()
    if "c:\\" in lowered:
        return True
    return any(trigger in lowered for trigger in OPERATOR_TRIGGERS)
