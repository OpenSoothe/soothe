"""One-line summary for academic_research completion display."""

from __future__ import annotations


def academic_research_report_summary_for_display(report: str, *, max_len: int = 160) -> str:
    """Return a single-line preview of the synthesized report."""
    text = (report or "").strip()
    if "\n\n" in text:
        text = text.split("\n\n", 1)[0].strip()
    text = " ".join(text.split())
    if len(text) <= max_len:
        return text
    return text[: max_len - 1] + "…"
