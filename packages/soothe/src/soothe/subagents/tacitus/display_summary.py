"""One-line summary for Tacitus completion display."""

from __future__ import annotations


def tacitus_answer_summary_for_display(answer: str, *, max_len: int = 160) -> str:
    """Return a single-line preview of the synthesized answer."""
    text = (answer or "").strip()
    if "\n\n" in text:
        text = text.split("\n\n", 1)[0].strip()
    text = " ".join(text.split())
    if len(text) <= max_len:
        return text
    return text[: max_len - 1] + "…"


__all__ = ["tacitus_answer_summary_for_display"]
