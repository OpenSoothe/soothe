"""Budgeted deferred-tool listing formatter."""

from __future__ import annotations

from collections.abc import Sequence
from typing import TypedDict

from soothe_nano.toolkits.progressive.registry import ToolDescriptor

# Section headers commonly appended to LangChain tool docstrings.
_SECTION_MARKERS: tuple[str, ...] = (
    "\nusage:",
    "\nparameters:",
    "\nreturns:",
    "\nexamples:",
    "\ninput should",
    "\nuse this when",
)

_MAX_NAME_COLUMN = 28


class ToolBudgetTelemetry(TypedDict):
    included_count: int
    truncated_count: int
    mode: str
    budget_chars: int
    actual_chars: int


def _normalize_tool_summary(description: str) -> str:
    """Collapse a tool docstring to a single scannable line."""
    text = description.strip()
    if not text:
        return ""

    lower = text.lower()
    cut = len(text)
    for marker in _SECTION_MARKERS:
        idx = lower.find(marker)
        if idx > 0:
            cut = min(cut, idx)
    text = text[:cut].strip()

    # Prefer the first non-empty line (drops trailing Usage bullet lists).
    first_line = next((ln.strip() for ln in text.splitlines() if ln.strip()), "")
    text = " ".join(first_line.split())

    # First sentence when it fits; otherwise keep the one-liner.
    for end in (". ", "! ", "? "):
        pos = text.find(end)
        if 0 < pos <= 140:
            return text[: pos + 1].strip()
    return text


def _truncate_at_word(text: str, max_len: int) -> str:
    """Truncate on a word boundary with an ellipsis marker."""
    if max_len <= 0:
        return ""
    if len(text) <= max_len:
        return text
    if max_len <= 1:
        return "…"
    body = text[: max_len - 1].rstrip()
    if " " in body:
        body = body.rsplit(" ", 1)[0]
    return body.rstrip(".,;:") + "…"


def _summarize(entry: ToolDescriptor, *, cap: int | None) -> str:
    summary = _normalize_tool_summary(entry.description or "")
    if cap is not None and summary and len(summary) > cap:
        summary = _truncate_at_word(summary, cap)
    return summary


def _format_entry_line(entry: ToolDescriptor, summary: str, *, name_width: int) -> str:
    if summary:
        name_col = entry.name[:_MAX_NAME_COLUMN].ljust(name_width)
        return f"  {name_col}  {summary}"
    return f"  {entry.name}"


def _render_entries(
    entries: Sequence[ToolDescriptor],
    *,
    cap: int | None,
) -> tuple[str, int]:
    """Render aligned listing; returns (text, truncated_count)."""
    if not entries:
        return "", 0

    summaries = [_summarize(e, cap=cap) for e in entries]
    truncated = sum(
        1
        for e, summary in zip(entries, summaries, strict=True)
        if summary and cap is not None and len(_normalize_tool_summary(e.description or "")) > cap
    )

    if not any(summaries):
        return "\n".join(f"  {e.name}" for e in entries), len(entries)

    name_width = min(max(len(e.name) for e in entries), _MAX_NAME_COLUMN)
    lines = [
        _format_entry_line(e, summary, name_width=name_width)
        for e, summary in zip(entries, summaries, strict=True)
    ]
    return "\n".join(lines), truncated


# Preamble injected by SystemPromptMiddleware before the listing body.
AVAILABLE_TOOLS_PREAMBLE = (
    "Deferred tools (not yet bound). Use search_tools(query) to find a tool, "
    "or call any name below to promote it for subsequent hops. "
    "There is no read_command — use run_command for shell output or grep to search files."
)


def format_tools_within_budget(
    entries: Sequence[ToolDescriptor],
    *,
    budget_chars: int,
    per_entry_cap_chars: int = 120,
    min_per_entry_chars: int = 20,
    include_preamble: bool = False,
) -> tuple[str, ToolBudgetTelemetry]:
    """Format deferred tool listing within a character budget."""
    if not entries:
        return "", ToolBudgetTelemetry(
            included_count=0,
            truncated_count=0,
            mode="full",
            budget_chars=budget_chars,
            actual_chars=0,
        )

    preamble = f"{AVAILABLE_TOOLS_PREAMBLE}\n\n" if include_preamble else ""
    preamble_len = len(preamble)
    body_budget = max(0, budget_chars - preamble_len)

    full_text, _ = _render_entries(entries, cap=None)
    if len(full_text) <= body_budget:
        text = preamble + full_text
        return text, ToolBudgetTelemetry(
            included_count=len(entries),
            truncated_count=0,
            mode="full",
            budget_chars=budget_chars,
            actual_chars=len(text),
        )

    raw_quota = body_budget // max(len(entries), 1)
    if raw_quota < min_per_entry_chars:
        names_only = "\n".join(f"  {e.name}" for e in entries)
        text = preamble + names_only
        return text, ToolBudgetTelemetry(
            included_count=len(entries),
            truncated_count=len(entries),
            mode="names_only",
            budget_chars=budget_chars,
            actual_chars=len(text),
        )

    quota = min(raw_quota, per_entry_cap_chars)
    truncated_text, truncated_count = _render_entries(entries, cap=quota)
    text = preamble + truncated_text
    return text, ToolBudgetTelemetry(
        included_count=len(entries),
        truncated_count=truncated_count,
        mode="truncated",
        budget_chars=budget_chars,
        actual_chars=len(text),
    )
