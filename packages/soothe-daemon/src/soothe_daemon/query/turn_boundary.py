"""Turn / stream boundary helpers for QueryEngine (IG-616)."""

from __future__ import annotations


def format_turn_id(loop_id: str, generation: int) -> str:
    """Return wire ``turn_id`` for ``loop_id`` + admit generation."""
    lid = str(loop_id or "").strip()
    gen = int(generation)
    if not lid or gen <= 0:
        return ""
    return f"{lid}:{gen}"


__all__ = ["format_turn_id"]
