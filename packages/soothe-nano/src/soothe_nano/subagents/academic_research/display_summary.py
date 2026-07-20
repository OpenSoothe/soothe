"""Summaries for academic_research completion display."""

from __future__ import annotations

import re

_SCOPE_HEADING_RE = re.compile(r"^#{1,3}\s+\**Scope\**:?\**", re.IGNORECASE | re.MULTILINE)
_SECTION_HEADING_RE = re.compile(r"^#{1,3}\s+(.+)$", re.MULTILINE)
_SKIP_HEADINGS = frozenset({"scope", "references"})
_PREFERRED_SUMMARY_SECTIONS = frozenset(
    {
        "executive summary",
        "key findings",
        "overview",
        "summary",
        "literature review",
        "synthesis",
        "conclusion",
    }
)


def _body_after_scope(report: str) -> str:
    """Return report text starting at the first section after Scope."""
    text = (report or "").strip()
    scope_match = _SCOPE_HEADING_RE.search(text)
    if not scope_match:
        return text
    remainder = text[scope_match.end() :]
    next_heading = _SECTION_HEADING_RE.search(remainder)
    if next_heading:
        return remainder[next_heading.start() :].lstrip()
    return remainder.lstrip()


def _first_content_paragraph(report: str) -> str:
    """Return the first non-heading paragraph after optional Scope section."""
    text = _body_after_scope(report)
    if not text:
        return ""

    chunks = [chunk.strip() for chunk in re.split(r"\n\s*\n", text) if chunk.strip()]
    for chunk in chunks:
        if chunk.startswith("#"):
            continue
        flattened = " ".join(chunk.split())
        if flattened:
            return flattened
    return " ".join((report or "").split())


def _clip_summary(text: str, *, max_len: int) -> str:
    flattened = " ".join(text.split())
    if len(flattened) <= max_len:
        return flattened
    return flattened[: max_len - 1] + "…"


def derive_report_title(report: str, topic: str) -> str:
    """Pick a human title from report headings, falling back to the research topic."""
    for match in _SECTION_HEADING_RE.finditer(report or ""):
        heading = match.group(1).strip()
        normalized = heading.strip("* ").lower()
        if normalized.startswith("scope:"):
            continue
        key = normalized.split(":", 1)[0].strip()
        if key in _SKIP_HEADINGS:
            continue
        if heading:
            return heading[:120]
    cleaned = (topic or "").strip()
    return cleaned[:120] if cleaned else "academic-report"


def academic_research_brief_summary_for_display(report: str, *, max_len: int = 320) -> str:
    """Return a short summary skipping boilerplate Scope headings."""
    text = (report or "").strip()
    if not text:
        return ""

    for match in _SECTION_HEADING_RE.finditer(text):
        heading = match.group(1).strip().strip("*").lower()
        if heading not in _PREFERRED_SUMMARY_SECTIONS:
            continue
        start = match.end()
        next_heading = _SECTION_HEADING_RE.search(text, start)
        section_body = text[start : next_heading.start() if next_heading else len(text)].strip()
        paragraph = _first_content_paragraph(section_body)
        if paragraph:
            return _clip_summary(paragraph, max_len=max_len)

    fallback = _first_content_paragraph(text)
    return _clip_summary(fallback, max_len=max_len) if fallback else ""
