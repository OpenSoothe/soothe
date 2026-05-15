"""Curated ``soothe.subagent.*`` wire protocol (metadata-only, IG-338).

Built-in subagents emit only allowlisted types with bounded string fields.
"""

from __future__ import annotations

from typing import Any

# --- Browser ---
SUBAGENT_BROWSER_STARTED = "soothe.subagent.browser.started"
SUBAGENT_BROWSER_COMPLETED = "soothe.subagent.browser.completed"
SUBAGENT_BROWSER_STEP_COMPLETED = "soothe.subagent.browser.step.completed"

# --- Claude ---
SUBAGENT_CLAUDE_STARTED = "soothe.subagent.claude.started"
SUBAGENT_CLAUDE_STEP_COMPLETED = "soothe.subagent.claude.step.completed"
SUBAGENT_CLAUDE_COMPLETED = "soothe.subagent.claude.completed"
SUBAGENT_CLAUDE_FAILED = "soothe.subagent.claude.failed"

# --- Explore ---
SUBAGENT_EXPLORE_STARTED = "soothe.subagent.explore.started"
SUBAGENT_EXPLORE_MILESTONE = "soothe.subagent.explore.milestone"
SUBAGENT_EXPLORE_STEP_COMPLETED = "soothe.subagent.explore.step.completed"
SUBAGENT_EXPLORE_COMPLETED = "soothe.subagent.explore.completed"

# --- Research ---
SUBAGENT_RESEARCH_STARTED = "soothe.subagent.research.started"
SUBAGENT_RESEARCH_GATHER_SUMMARY = "soothe.subagent.research.gather.summary"
SUBAGENT_RESEARCH_COMPLETED = "soothe.subagent.research.completed"

ALLOWLISTED_SUBAGENT_EVENT_TYPES: frozenset[str] = frozenset(
    {
        SUBAGENT_BROWSER_STARTED,
        SUBAGENT_BROWSER_COMPLETED,
        SUBAGENT_BROWSER_STEP_COMPLETED,
        SUBAGENT_CLAUDE_STARTED,
        SUBAGENT_CLAUDE_STEP_COMPLETED,
        SUBAGENT_CLAUDE_COMPLETED,
        SUBAGENT_CLAUDE_FAILED,
        SUBAGENT_EXPLORE_STARTED,
        SUBAGENT_EXPLORE_MILESTONE,
        SUBAGENT_EXPLORE_STEP_COMPLETED,
        SUBAGENT_EXPLORE_COMPLETED,
        SUBAGENT_RESEARCH_STARTED,
        SUBAGENT_RESEARCH_GATHER_SUMMARY,
        SUBAGENT_RESEARCH_COMPLETED,
    }
)

_DEFAULT_PREVIEW_LEN = 120
_LONG_PREVIEW_LEN = 200
# Task-oriented fields (e.g. explore search_target) may be full user sentences
_TASK_DESCRIPTION_LEN = 8000


def is_allowlisted_subagent_event_type(event_type: str) -> bool:
    """Return True when ``event_type`` is an allowlisted curated subagent wire event."""
    return event_type in ALLOWLISTED_SUBAGENT_EVENT_TYPES


def parse_subagent_wire_agent(event_type: str) -> str | None:
    """Return agent segment (``browser``, ``claude``, …) from ``soothe.subagent.<agent>.…``."""
    parts = event_type.split(".")
    if len(parts) >= 4 and parts[0] == "soothe" and parts[1] == "subagent":
        return parts[2]
    return None


def truncate_wire_str(value: str, max_len: int = _DEFAULT_PREVIEW_LEN) -> str:
    """Truncate a single wire string field."""
    if len(value) <= max_len:
        return value
    if max_len <= 1:
        return "…"
    return value[: max_len - 1] + "…"


def clip_wire_event_payload(data: dict[str, Any]) -> dict[str, Any]:
    """Copy event dict and truncate known string fields for wire safety."""
    out = dict(data)
    string_caps: dict[str, int] = {
        "task_preview": _LONG_PREVIEW_LEN,
        "topic": _LONG_PREVIEW_LEN,
        "search_target": _TASK_DESCRIPTION_LEN,
        "task": _LONG_PREVIEW_LEN,
        "judgement": _LONG_PREVIEW_LEN,
        "message": _LONG_PREVIEW_LEN,
        "error": _LONG_PREVIEW_LEN,
        "action_preview": _DEFAULT_PREVIEW_LEN,
        "tool_name": _DEFAULT_PREVIEW_LEN,
        "input_preview": _DEFAULT_PREVIEW_LEN,
        "summary": _LONG_PREVIEW_LEN,
        "url": _LONG_PREVIEW_LEN,
        "title": _DEFAULT_PREVIEW_LEN,
        "query_preview": _DEFAULT_PREVIEW_LEN,
        "args_preview": _DEFAULT_PREVIEW_LEN,
        "result_preview": _DEFAULT_PREVIEW_LEN,
    }
    for key, cap in string_caps.items():
        val = out.get(key)
        if isinstance(val, str):
            out[key] = truncate_wire_str(val, cap)
    return out


__all__ = [
    "ALLOWLISTED_SUBAGENT_EVENT_TYPES",
    "SUBAGENT_BROWSER_COMPLETED",
    "SUBAGENT_BROWSER_STARTED",
    "SUBAGENT_BROWSER_STEP_COMPLETED",
    "SUBAGENT_CLAUDE_COMPLETED",
    "SUBAGENT_CLAUDE_FAILED",
    "SUBAGENT_CLAUDE_STARTED",
    "SUBAGENT_CLAUDE_STEP_COMPLETED",
    "SUBAGENT_EXPLORE_COMPLETED",
    "SUBAGENT_EXPLORE_MILESTONE",
    "SUBAGENT_EXPLORE_STEP_COMPLETED",
    "SUBAGENT_EXPLORE_STARTED",
    "SUBAGENT_RESEARCH_COMPLETED",
    "SUBAGENT_RESEARCH_GATHER_SUMMARY",
    "SUBAGENT_RESEARCH_STARTED",
    "clip_wire_event_payload",
    "is_allowlisted_subagent_event_type",
    "parse_subagent_wire_agent",
    "truncate_wire_str",
]
