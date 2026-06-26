"""Deterministic explore results when LLM synthesis or the graph fails (RFC-613)."""

from __future__ import annotations

import logging
from typing import Any, Literal

from .schemas import ExploreResult, MatchEntry

logger = logging.getLogger(__name__)

ExploreCompletionStatus = Literal["complete", "partial", "failed"]
_VALID_RELEVANCE = frozenset({"high", "medium", "low"})


def _normalize_relevance(raw: Any) -> Literal["high", "medium", "low"]:
    value = str(raw or "").strip().lower()
    if value in _VALID_RELEVANCE:
        return value  # type: ignore[return-value]
    return "medium"


def build_explore_result_from_findings(
    findings: list[dict[str, Any]],
    *,
    search_target: str,
    thoroughness: str = "medium",
    max_matches: int,
    status: ExploreCompletionStatus,
    failure_reason: str = "",
) -> ExploreResult:
    """Build an ``ExploreResult`` from accumulated tool findings without LLM synthesis.

    Args:
        findings: Rows collected by ``ExploreFindingsMiddleware``.
        search_target: Resolved search target for the run.
        thoroughness: Configured thoroughness label (defaults to "medium" if omitted).
        max_matches: Cap on returned matches.
        status: ``partial`` when findings exist but synthesis failed; ``failed`` when empty.
        failure_reason: Short operator-facing reason (logged and surfaced in coverage).

    Returns:
        Structured explore output suitable for delegate markdown formatting.
    """
    matches: list[MatchEntry] = []
    seen_paths: set[str] = set()
    for row in findings:
        path = str(row.get("path") or "unknown").strip() or "unknown"
        if path in seen_paths:
            continue
        seen_paths.add(path)
        snippet_raw = row.get("snippet")
        snippet = (
            str(snippet_raw).strip()[:400]
            if isinstance(snippet_raw, str) and snippet_raw.strip()
            else None
        )
        description_source = snippet or path
        description = description_source.replace("\n", " ").strip()
        if len(description) > 80:
            description = description[:79] + "…"
        matches.append(
            MatchEntry(
                path=path,
                relevance=_normalize_relevance(row.get("relevance")),
                description=description or path,
                snippet=snippet,
            )
        )
        if len(matches) >= max_matches:
            break

    reason = (failure_reason or "").strip()
    if status == "partial":
        summary = (
            f"Partial explore results: {len(findings)} evidence item(s) collected"
            f" ({len(matches)} path(s) listed below)."
        )
        if reason:
            summary += f" Synthesis did not complete: {reason}"
        gaps = (
            "Explore ended with partial results. LLM synthesis failed or was skipped; "
            "matches below are derived directly from tool outputs."
        )
        if reason:
            gaps += f" Reason: {reason}"
    elif status == "failed":
        summary = "Explore did not complete successfully."
        gaps = reason or "No findings were collected before explore stopped."
    else:
        summary = f"Explore found {len(matches)} match(es) for the search target."
        gaps = reason

    logger.log(
        logging.WARNING if status == "partial" else logging.ERROR,
        "Explore: built %s result (%d findings → %d matches)%s",
        status,
        len(findings),
        len(matches),
        f" reason={reason!r}" if reason else "",
    )

    return ExploreResult(
        target=search_target or "unknown",
        thoroughness=thoroughness,
        matches=matches,
        summary=summary,
        suggested_next_actions=(
            "- Review the listed paths with read_file or grep before continuing." if matches else ""
        ),
        coverage_gaps=gaps,
        architecture_notes="",
    )
