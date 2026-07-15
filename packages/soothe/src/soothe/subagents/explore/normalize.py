"""Normalization helpers for explorer structured synthesis output."""

from __future__ import annotations

from typing import Any

_VALID_RELEVANCE = {"high", "medium", "low"}


def _normalize_relevance(value: Any) -> str:
    """Return supported relevance label with deterministic fallback."""
    normalized = str(value or "").strip().lower()
    if normalized in _VALID_RELEVANCE:
        return normalized
    return "medium"


def _normalize_match_entry(raw: dict[str, Any]) -> dict[str, Any]:
    """Normalize one raw match item into ExploreResult.MatchEntry shape."""
    path = str(raw.get("path") or raw.get("file") or raw.get("location") or "").strip()
    description = str(
        raw.get("description") or raw.get("summary") or raw.get("reason") or path
    ).strip()
    snippet_raw = raw.get("snippet")
    snippet = str(snippet_raw).strip() if isinstance(snippet_raw, str) else ""
    out: dict[str, Any] = {
        "path": path or "unknown",
        "relevance": _normalize_relevance(raw.get("relevance")),
        "description": description or "Matched path",
    }
    if snippet:
        out["snippet"] = snippet
    return out


def coerce_explore_result_dict(
    data: dict[str, Any],
    *,
    search_target: str,
    thoroughness: str,
    max_matches: int,
) -> dict[str, Any]:
    """Coerce provider output into a strict ExploreResult-compatible payload."""
    normalized = dict(data or {})
    matches_raw = normalized.get("matches")
    if not isinstance(matches_raw, list):
        for alias in ("items", "results", "entries"):
            candidate = normalized.get(alias)
            if isinstance(candidate, list):
                matches_raw = candidate
                break
    if not isinstance(matches_raw, list):
        matches_raw = []

    normalized_matches: list[dict[str, Any]] = []
    for row in matches_raw:
        if isinstance(row, dict):
            normalized_matches.append(_normalize_match_entry(row))
        elif isinstance(row, str) and row.strip():
            normalized_matches.append(
                {
                    "path": row.strip(),
                    "relevance": "medium",
                    "description": row.strip(),
                }
            )
        if len(normalized_matches) >= max(1, int(max_matches)):
            break

    summary = str(normalized.get("summary") or "").strip()
    if not summary:
        if normalized_matches:
            summary = f"Found {len(normalized_matches)} candidate path(s) for '{search_target}'."
        else:
            summary = f"No ranked matches were returned for '{search_target}'."

    # Keep target stable: synthesized payloads may paraphrase or over-expand it.
    normalized["target"] = str(search_target or "unknown")
    normalized["thoroughness"] = str(normalized.get("thoroughness") or thoroughness or "medium")
    normalized["matches"] = normalized_matches
    normalized["summary"] = summary
    normalized["suggested_next_actions"] = str(normalized.get("suggested_next_actions") or "")
    normalized["coverage_gaps"] = str(normalized.get("coverage_gaps") or "")
    normalized["architecture_notes"] = str(normalized.get("architecture_notes") or "")
    return normalized


__all__ = ["coerce_explore_result_dict"]
