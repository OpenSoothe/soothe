"""One-line summary for research subagent completion display (IG-344)."""

from __future__ import annotations


def research_answer_summary_for_display(answer: str, *, max_len: int = 160) -> str:
    """First paragraph (block before a blank line), collapsed to one line."""
    raw = (answer or "").strip()
    if not raw:
        return ""
    first_block = raw.split("\n\n", 1)[0].strip()
    first_line = first_block.split("\n", 1)[0].strip()
    out = " ".join(first_line.split())
    if len(out) > max_len:
        return out[: max_len - 1] + "…"
    return out


__all__ = ["research_answer_summary_for_display"]
