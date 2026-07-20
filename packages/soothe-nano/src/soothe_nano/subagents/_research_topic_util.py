"""Helpers for research topics that may include host attachment bodies.

Attached file extracts (for example Triarch PDF text) may be present so
PlanResearch can derive a concise topic plus search queries. Downstream nodes —
especially Synthesize — must receive only the extracted topic, never file bodies.
"""

from __future__ import annotations

from typing import Any

_CUT_MARKERS = (
    "--- Context ---",
    "--- Triarch attachments (extracted content) ---",
)
_UI_LANGUAGE_MARKER = "--- Triarch UI language ---"
_MAX_PLANNED_TOPIC_LEN = 800


def ui_language_suffix(topic: str) -> str:
    """Return the ``--- Triarch UI language ---`` block when present."""
    text = topic or ""
    idx = text.find(_UI_LANGUAGE_MARKER)
    if idx == -1:
        return ""
    return text[idx:].lstrip()


def topic_without_attachments(topic: str) -> str:
    """Return the user ask (and optional UI-language footer), without file bodies.

    Fallback when PlanResearch does not return an extracted ``research_topic``.
    """
    text = topic or ""
    ui_suffix = ui_language_suffix(text)
    if ui_suffix:
        text = text[: text.find(_UI_LANGUAGE_MARKER)]

    cut = len(text)
    for marker in _CUT_MARKERS:
        idx = text.find(marker)
        if idx != -1:
            cut = min(cut, idx)
    cleaned = text[:cut].strip()
    return _join_topic_and_ui(cleaned, ui_suffix)


def planned_research_topic(parsed: dict[str, Any] | None, raw_topic: str) -> str:
    """Prefer LLM-extracted topic from PlanResearch; else strip attachments.

    Always drops attachment bodies and re-attaches any UI-language directive from
    the original host prompt so synthesis can honor display locale.
    """
    ui_suffix = ui_language_suffix(raw_topic)
    candidate = ""
    if isinstance(parsed, dict):
        for key in ("research_topic", "topic"):
            value = parsed.get(key)
            if isinstance(value, str) and value.strip():
                candidate = value.strip()
                break
    if not candidate:
        candidate = topic_without_attachments(raw_topic)
        # topic_without_attachments already includes UI suffix
        return (
            candidate[:_MAX_PLANNED_TOPIC_LEN]
            if len(candidate) > _MAX_PLANNED_TOPIC_LEN
            else candidate
        )

    # Guard: model must not echo attachment/context blocks into research_topic.
    for marker in _CUT_MARKERS:
        idx = candidate.find(marker)
        if idx != -1:
            candidate = candidate[:idx].strip()
    ui_in_candidate = candidate.find(_UI_LANGUAGE_MARKER)
    if ui_in_candidate != -1:
        candidate = candidate[:ui_in_candidate].strip()

    if len(candidate) > _MAX_PLANNED_TOPIC_LEN:
        candidate = candidate[:_MAX_PLANNED_TOPIC_LEN].rstrip() + "…"
    return _join_topic_and_ui(candidate, ui_suffix)


def _join_topic_and_ui(topic: str, ui_suffix: str) -> str:
    cleaned = (topic or "").strip()
    if not ui_suffix:
        return cleaned
    if cleaned:
        return f"{cleaned}\n\n{ui_suffix}"
    return ui_suffix
