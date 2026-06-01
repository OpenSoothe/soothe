"""One-line summary for browser_use subagent completion display (IG-344)."""

from __future__ import annotations


def browser_use_result_summary_for_display(result: str, *, max_len: int = 160) -> str:
    """First non-empty line from browser-use ``final_result()`` style markdown/prose."""
    for line in (result or "").split("\n"):
        s = line.strip()
        if s:
            out = " ".join(s.split())
            if len(out) > max_len:
                return out[: max_len - 1] + "…"
            return out
    return ""


__all__ = ["browser_use_result_summary_for_display"]
