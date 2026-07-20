"""RFC-105: Budgeted skill-listing formatter (Claude Code parity)."""

from __future__ import annotations

from collections.abc import Sequence
from typing import TypedDict

from soothe_nano.skills.index import SkillIndexEntry


class BudgetTelemetry(TypedDict):
    included_count: int
    truncated_count: int
    mode: str  # "full" | "truncated" | "names_only"
    budget_chars: int
    actual_chars: int


def _is_builtin(e: SkillIndexEntry) -> bool:
    return e.source == "builtin"


def _format_entry(e: SkillIndexEntry, *, cap: int | None) -> str:
    name = e.name
    desc = e.description or ""
    if cap is not None and len(desc) > cap:
        desc = desc[: max(0, cap - 1)].rstrip() + "…"
    wt = (e.when_to_use or "").strip()
    if wt and cap is not None:
        remaining = max(0, cap - len(desc))
        if remaining > 10:
            wt_trim = wt[:remaining]
            return f"- {name}: {desc}\n  When to use: {wt_trim}"
    if wt and cap is None:
        return f"- {name}: {desc}\n  When to use: {wt}"
    return f"- {name}: {desc}"


def format_skills_within_budget(
    entries: Sequence[SkillIndexEntry],
    *,
    budget_chars: int,
    per_entry_cap_chars: int = 250,
    min_per_entry_chars: int = 20,
) -> tuple[str, BudgetTelemetry]:
    """Format skill listing within a character budget.

    Modes:
      - "full"        — under budget, every entry gets full description
      - "truncated"   — over budget, non-built-ins share remaining budget;
                        built-ins always keep full description
      - "names_only"  — extreme case (per-entry quota < min), non-built-ins
                        become names-only; built-ins keep full description

    Args:
        entries: Skill entries to format.
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

    # Over budget: built-ins keep full description; share remaining among non-builtins.
    builtins = [e for e in entries if _is_builtin(e)]
    others = [e for e in entries if not _is_builtin(e)]
    builtin_text = "\n".join(_format_entry(e, cap=None) for e in builtins)
    used = len(builtin_text) + 1
    remaining = max(0, budget_chars - used)
    raw_quota = (remaining // max(1, len(others))) if others else 0
    quota = min(raw_quota, per_entry_cap_chars)

    if quota < min_per_entry_chars and others:
        # names-only mode for non-builtins
        names = "\n".join(f"- {e.name}" for e in others)
        text = (builtin_text + "\n" + names) if builtin_text else names
        return text, BudgetTelemetry(
            included_count=len(entries),
            truncated_count=len(others),
            mode="names_only",
            budget_chars=budget_chars,
            actual_chars=len(text),
        )

    others_text = "\n".join(_format_entry(e, cap=quota) for e in others)
    text = (
        (builtin_text + ("\n" + others_text if others_text else ""))
        if builtin_text
        else others_text
    )
    return text, BudgetTelemetry(
        included_count=len(entries),
        truncated_count=sum(1 for e in others if len(e.description) > quota),
        mode="truncated",
        budget_chars=budget_chars,
        actual_chars=len(text),
    )
