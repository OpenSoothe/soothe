"""RFC-412: Budgeted MCP tool-listing formatter.

Same algorithm as skills/budget.py but typed to MCPToolDescriptor instead of SkillIndexEntry.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import TypedDict


@dataclass(frozen=True, slots=True)
class MCPToolDescriptor:
    """Descriptor for a deferred MCP tool (RFC-412)."""

    name: str  # mangled: mcp__<server>__<tool>
    bare_name: str  # original tool name from the server
    description: str
    server: str  # server name
    is_essential: bool  # True if server has defer=False (always-loaded)


class BudgetTelemetry(TypedDict):
    included_count: int
    truncated_count: int
    mode: str  # "full" | "truncated" | "names_only"
    budget_chars: int
    actual_chars: int


def _is_essential(e: MCPToolDescriptor) -> bool:
    return e.is_essential


def _format_entry(e: MCPToolDescriptor, *, cap: int | None) -> str:
    name = e.name
    desc = e.description or ""
    if cap is not None and len(desc) > cap:
        desc = desc[: max(0, cap - 1)].rstrip() + "…"
    return f"- {name}: {desc}"


def format_mcp_tools_within_budget(
    entries: Sequence[MCPToolDescriptor],
    *,
    budget_chars: int,
    per_entry_cap_chars: int = 250,
    min_per_entry_chars: int = 20,
) -> tuple[str, BudgetTelemetry]:
    """Format MCP tool listing within a character budget (RFC-412).

    Modes:
      - "full"        — under budget, every entry gets full description
      - "truncated"   — over budget, essential tools (is_essential=True) keep
                        full description; others share remaining budget
      - "names_only"  — extreme case (per-entry quota < min), non-essential
                        entries become names-only; essential keep full description

    Args:
        entries: MCP tool descriptors to format.
        budget_chars: Total character budget for the listing.
        per_entry_cap_chars: Hard per-entry character cap.
        min_per_entry_chars: Below this threshold, fall back to names-only.

    Returns:
        Tuple of (formatted_text, telemetry).
    """
    if not entries:
        return "", BudgetTelemetry(
            included_count=0,
            truncated_count=0,
            mode="full",
            budget_chars=budget_chars,
            actual_chars=0,
        )

    full_rendered = [_format_entry(e, cap=None) for e in entries]
    total_full = sum(len(r) + 1 for r in full_rendered)
    if total_full <= budget_chars:
        text = "\n".join(full_rendered)
        return text, BudgetTelemetry(
            included_count=len(entries),
            truncated_count=0,
            mode="full",
            budget_chars=budget_chars,
            actual_chars=len(text),
        )

    # Over budget: essential keep full description; share remaining among non-essential.
    essential = [e for e in entries if _is_essential(e)]
    others = [e for e in entries if not _is_essential(e)]
    essential_text = "\n".join(_format_entry(e, cap=None) for e in essential)
    used = len(essential_text) + 1
    remaining = max(0, budget_chars - used)
    raw_quota = (remaining // max(1, len(others))) if others else 0
    quota = min(raw_quota, per_entry_cap_chars)

    if quota < min_per_entry_chars and others:
        # names-only mode for non-essential
        names = "\n".join(f"- {e.name}" for e in others)
        text = (essential_text + "\n" + names) if essential_text else names
        return text, BudgetTelemetry(
            included_count=len(entries),
            truncated_count=len(others),
            mode="names_only",
            budget_chars=budget_chars,
            actual_chars=len(text),
        )

    others_text = "\n".join(_format_entry(e, cap=quota) for e in others)
    text = (
        (essential_text + ("\n" + others_text if others_text else ""))
        if essential_text
        else others_text
    )
    return text, BudgetTelemetry(
        included_count=len(entries),
        truncated_count=sum(1 for e in others if len(e.description) > quota),
        mode="truncated",
        budget_chars=budget_chars,
        actual_chars=len(text),
    )
