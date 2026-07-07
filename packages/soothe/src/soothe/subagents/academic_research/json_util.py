"""JSON extraction helpers for Academic Research LLM nodes."""

from __future__ import annotations

import json
import re
from typing import Any


def llm_response_text(response: Any) -> str:
    """Return parseable text from an AIMessage-like response.

    Thinking models (e.g. GLM) may put JSON in ``additional_kwargs["reasoning_content"]``
    while leaving ``content`` empty or minimal.
    """
    if hasattr(response, "content") and response.content:
        return str(response.content)
    kwargs = getattr(response, "additional_kwargs", None) or {}
    if isinstance(kwargs, dict):
        reasoning = kwargs.get("reasoning_content")
        if reasoning:
            return str(reasoning)
    return str(response)


def parse_json_object(content: str) -> dict[str, Any] | None:
    """Parse a JSON object from model output (raw or markdown-fenced)."""
    text = (content or "").strip()
    if not text:
        return None

    fence = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", text, re.DOTALL | re.IGNORECASE)
    if fence:
        text = fence.group(1).strip()

    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass

    start = text.find("{")
    if start >= 0:
        depth = 0
        for i, ch in enumerate(text[start:], start=start):
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    try:
                        parsed = json.loads(text[start : i + 1])
                        if isinstance(parsed, dict):
                            return parsed
                    except json.JSONDecodeError:
                        break
    return None


def compact_search_query(raw: str, *, max_len: int = 120) -> str:
    """Reduce a long task prompt to a short search-engine query."""
    text = (raw or "").strip()
    for sep in ("\n\n", "\n1.", "\n2.", "\n请", "\nPlease", "\nUse ", "\n使用"):
        if sep in text:
            text = text.split(sep, 1)[0].strip()
    text = " ".join(text.split())
    if len(text) > max_len:
        return text[: max_len - 1] + "…"
    return text


def fallback_sub_questions(topic: str, *, domain: str = "public") -> list[dict[str, str]]:
    """Single sub-question derived from the research topic."""
    _ = domain
    return [{"question": compact_search_query(topic, max_len=200)}]


def fallback_queries(
    topic: str,
    sub_questions: list[Any] | None = None,
    *,
    default_domain: str = "public",
) -> list[dict[str, str]]:
    """Build search queries from sub-questions or the topic."""
    _ = default_domain
    queries: list[dict[str, str]] = []
    for sq in sub_questions or []:
        if isinstance(sq, dict):
            question = str(sq.get("question", "")).strip()
        else:
            question = str(sq).strip()
        if not question:
            continue
        queries.append({"query": compact_search_query(question, max_len=120)})
    if queries:
        return queries
    return [{"query": compact_search_query(topic, max_len=120)}]
