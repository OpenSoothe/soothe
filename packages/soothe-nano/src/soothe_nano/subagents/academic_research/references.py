"""Reference collection and bibliography formatting for Academic Research."""

from __future__ import annotations

import re
from urllib.parse import urlparse

from .protocol import ResearchReference, SourceResult

_URL_IN_TEXT = re.compile(r"https?://[^\s\])>\"']+")


def reference_from_source_result(
    result: SourceResult,
    *,
    query: str | None = None,
) -> ResearchReference:
    """Build a structured reference from a gather ``SourceResult``."""
    meta = result.metadata or {}
    url = meta.get("url") or meta.get("link")
    if not url and result.source_ref.startswith(("http://", "https://")):
        url = result.source_ref
    if not url:
        found = _URL_IN_TEXT.search(result.content or "")
        if found:
            url = found.group(0).rstrip(".,;)")
    title = meta.get("title") or meta.get("domain")
    if not title and url:
        try:
            host = urlparse(str(url)).hostname or ""
            title = host.removeprefix("www.") or None
        except Exception:
            title = None
    if not title:
        title = result.source_ref if result.source_ref else result.source_name
    return ResearchReference(
        url=str(url) if url else None,
        title=str(title) if title else None,
        source_name=result.source_name,
        source_ref=result.source_ref,
        query=query,
    )


def _reference_key(ref: ResearchReference) -> str:
    if ref.url:
        parsed = urlparse(ref.url.strip().rstrip("/"))
        host = (parsed.hostname or "").lower()
        path = parsed.path.rstrip("/")
        return f"url:{host}{path}"
    return f"ref:{ref.source_name}:{ref.source_ref}".lower()


def merge_references(refs: list[ResearchReference]) -> list[ResearchReference]:
    """Deduplicate references while preserving first-seen order."""
    seen: set[str] = set()
    merged: list[ResearchReference] = []
    for ref in refs:
        key = _reference_key(ref)
        if key in seen:
            continue
        seen.add(key)
        merged.append(ref)
    return merged


def format_references_section(
    refs: list[ResearchReference],
    *,
    accessed_date: str | None = None,
) -> str:
    """Format a markdown bibliography section."""
    if not refs:
        return ""
    lines = ["## References", ""]
    for idx, ref in enumerate(refs, 1):
        label = (ref.title or ref.source_ref or ref.source_name).strip()
        if ref.url:
            entry = f"{idx}. [{label}]({ref.url})"
        else:
            entry = f"{idx}. {label} ({ref.source_name}: {ref.source_ref})"
        if accessed_date:
            entry += f" (accessed {accessed_date})"
        lines.append(entry)
    return "\n".join(lines)


__all__ = [
    "format_references_section",
    "merge_references",
    "reference_from_source_result",
]
