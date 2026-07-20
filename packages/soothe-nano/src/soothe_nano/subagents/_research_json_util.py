"""Shared JSON and query helpers for research subagents."""

from __future__ import annotations

from typing import Any

from soothe_nano.utils.llm.response_text import llm_response_text, parse_json_object

__all__ = [
    "compact_search_query",
    "fallback_queries",
    "fallback_sub_questions",
    "llm_response_text",
    "parse_json_object",
]


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
