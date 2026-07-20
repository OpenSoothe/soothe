"""Generic subagent spec helpers for Coding CoreAgent (no host intake policy)."""

from __future__ import annotations

from typing import Any


def spec_subagent_name(spec: Any) -> str | None:
    """Best-effort name from a SubAgent / CompiledSubAgent dict or object."""
    if isinstance(spec, dict):
        raw = spec.get("name")
        return raw.strip() if isinstance(raw, str) and raw.strip() else None
    raw_name = getattr(spec, "name", None)
    if isinstance(raw_name, str) and raw_name.strip():
        return raw_name.strip()
    return None


__all__ = ["spec_subagent_name"]
