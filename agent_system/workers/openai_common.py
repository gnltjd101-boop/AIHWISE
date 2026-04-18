from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any


OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
OPENAI_BASE_URL = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1")


def openai_available() -> bool:
    return bool(OPENAI_API_KEY)


def openai_request(path: str, body: dict[str, Any]) -> dict[str, Any]:
    if not OPENAI_API_KEY:
        raise RuntimeError("OPENAI_API_KEY is not set.")
    request = urllib.request.Request(
        url=f"{OPENAI_BASE_URL}{path}",
        method="POST",
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {OPENAI_API_KEY}",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            raw = response.read().decode("utf-8")
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        error_body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"OpenAI API error {exc.code}: {error_body}") from exc


def extract_output_text(response: dict[str, Any]) -> str:
    parts: list[str] = []
    for output_item in response.get("output", []):
        if output_item.get("type") != "message":
            continue
        for content in output_item.get("content", []):
            if content.get("type") == "output_text":
                parts.append(str(content.get("text") or ""))
    return "\n".join(part for part in parts if part.strip()).strip()


def safe_text_response(
    developer_text: str,
    user_payload: Any,
    *,
    model: str = "gpt-5.4-mini",
    reasoning_effort: str = "low",
    tools: list[dict[str, Any]] | None = None,
) -> str | None:
    if not openai_available():
        return None
    response = openai_request(
        "/responses",
        {
            "model": model,
            "reasoning": {"effort": reasoning_effort},
            "tools": tools or [],
            "input": [
                {"role": "developer", "content": developer_text},
                {
                    "role": "user",
                    "content": json.dumps(user_payload, ensure_ascii=False) if isinstance(user_payload, (dict, list)) else str(user_payload),
                },
            ],
        },
    )
    text = extract_output_text(response)
    return text or None


def safe_json_response(
    developer_text: str,
    user_payload: Any,
    *,
    model: str = "gpt-5.4-mini",
    reasoning_effort: str = "low",
    tools: list[dict[str, Any]] | None = None,
) -> dict[str, Any] | None:
    text = safe_text_response(
        developer_text,
        user_payload,
        model=model,
        reasoning_effort=reasoning_effort,
        tools=tools,
    )
    if not text:
        return None
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None
