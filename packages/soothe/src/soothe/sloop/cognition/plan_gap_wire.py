"""Wire coercion for PlanGapAnalysis structured LLM output.

Models sometimes emit ``name`` (or similar) instead of the schema field
``component`` on ``components[]`` items, omit ``component`` entirely, or
overflow ``max_length`` string fields. Coerce before jsonschema validation
so a single alias slip cannot abort the StrangeLoop graph.
"""

from __future__ import annotations

from typing import Any

# Alias keys models use for GoalComponentStatus.component (first wins).
_COMPONENT_ALIASES: tuple[str, ...] = ("name", "title", "label", "facet", "aspect")

_STATUS_ALIASES: dict[str, str] = {
    "done": "satisfied",
    "complete": "satisfied",
    "completed": "satisfied",
    "ok": "satisfied",
    "success": "satisfied",
    "met": "satisfied",
    "open": "not_started",
    "todo": "not_started",
    "pending": "not_started",
    "in_progress": "partial",
    "progress": "partial",
    "wip": "partial",
    "stuck": "blocked",
    "failed": "blocked",
    "fail": "blocked",
    "error": "blocked",
}

_DISTANCE_ALIASES: dict[str, str] = {
    "close": "near",
    "almost": "near",
    "done": "at_goal",
    "complete": "at_goal",
    "completed": "at_goal",
    "finished": "at_goal",
    "reached": "at_goal",
    "mid": "moderate",
    "medium": "moderate",
    "distant": "far",
}

_VALID_STATUSES = frozenset({"not_started", "partial", "satisfied", "blocked"})
_VALID_DISTANCES = frozenset({"far", "moderate", "near", "at_goal"})

# Keep in sync with PlanGapAnalysis / GoalComponentStatus Field max_length.
_COMPONENT_MAX = 120
_EVIDENCE_MAX = 2048
_GAP_MAX = 2048
_SUMMARY_MAX = 2048
_REASONING_MAX = 2048
_COMPONENTS_MAX = 8
_REMAINING_GAPS_MAX = 6


def _clip_str(value: Any, max_len: int) -> str:
    text = value if isinstance(value, str) else ("" if value is None else str(value))
    text = text.strip()
    if len(text) <= max_len:
        return text
    if max_len <= 3:
        return text[:max_len]
    return text[: max_len - 3].rstrip() + "..."


def _normalize_status(raw: Any) -> str:
    if not isinstance(raw, str):
        return "partial"
    key = raw.strip().lower().replace("-", "_").replace(" ", "_")
    if key in _VALID_STATUSES:
        return key
    mapped = _STATUS_ALIASES.get(key)
    if mapped in _VALID_STATUSES:
        return mapped
    return "partial"


def _normalize_distance(raw: Any) -> str:
    if not isinstance(raw, str):
        return "moderate"
    key = raw.strip().lower().replace("-", "_").replace(" ", "_")
    if key in _VALID_DISTANCES:
        return key
    mapped = _DISTANCE_ALIASES.get(key)
    if mapped in _VALID_DISTANCES:
        return mapped
    return "moderate"


def coerce_goal_component_status_dict(data: Any, *, index: int = 0) -> Any:
    """Map wire aliases onto ``component`` for one GoalComponentStatus dict."""
    if not isinstance(data, dict):
        return data
    entry = dict(data)
    component = entry.get("component")
    if not (isinstance(component, str) and component.strip()):
        for alias in _COMPONENT_ALIASES:
            raw = entry.get(alias)
            if isinstance(raw, str) and raw.strip():
                entry["component"] = raw.strip()
                break
    for alias in _COMPONENT_ALIASES:
        entry.pop(alias, None)

    component = entry.get("component")
    if not (isinstance(component, str) and component.strip()):
        evidence = entry.get("evidence")
        if isinstance(evidence, str) and evidence.strip():
            # First clause / line of evidence as a synthetic facet label.
            head = evidence.strip().split("\n", 1)[0]
            head = head.split(".", 1)[0].strip() or evidence.strip()
            entry["component"] = _clip_str(head, _COMPONENT_MAX) or f"component_{index + 1}"
        else:
            entry["component"] = f"component_{index + 1}"
    else:
        entry["component"] = _clip_str(component, _COMPONENT_MAX) or f"component_{index + 1}"

    entry["status"] = _normalize_status(entry.get("status"))
    entry["evidence"] = _clip_str(entry.get("evidence", ""), _EVIDENCE_MAX)
    entry["gap"] = _clip_str(entry.get("gap", ""), _GAP_MAX)
    return entry


def coerce_plan_gap_analysis_wire_dict(data: dict[str, Any]) -> dict[str, Any]:
    """Salvage common PlanGapAnalysis wire malformations before validation.

    Args:
        data: Parsed structured-output dict (may already be valid).

    Returns:
        Dict safe for ``PlanGapAnalysis`` jsonschema / Pydantic construction.
    """
    if not isinstance(data, dict):
        return data

    out = dict(data)
    components = out.get("components")
    if not isinstance(components, list) or not components:
        # Minimal salvage so schema min_length=1 can still pass after coerce.
        out["components"] = [
            {
                "component": "goal",
                "status": "partial",
                "evidence": _clip_str(out.get("evidence_summary", ""), _EVIDENCE_MAX),
                "gap": "",
            }
        ]
    else:
        coerced_components = [
            coerce_goal_component_status_dict(item, index=i)
            for i, item in enumerate(components[:_COMPONENTS_MAX])
        ]
        out["components"] = [c for c in coerced_components if isinstance(c, dict)]
        if not out["components"]:
            out["components"] = [
                {
                    "component": "goal",
                    "status": "partial",
                    "evidence": "",
                    "gap": "",
                }
            ]

    out["evidence_summary"] = _clip_str(out.get("evidence_summary", ""), _SUMMARY_MAX)
    if not out["evidence_summary"]:
        # Prefer first component evidence over an empty required string.
        first = out["components"][0]
        out["evidence_summary"] = (
            _clip_str(first.get("evidence", ""), _SUMMARY_MAX) or "see components"
        )

    remaining = out.get("remaining_gaps")
    if isinstance(remaining, list):
        clipped: list[str] = []
        for item in remaining[:_REMAINING_GAPS_MAX]:
            text = _clip_str(item, _GAP_MAX)
            if text:
                clipped.append(text)
        out["remaining_gaps"] = clipped
    elif remaining is None:
        out["remaining_gaps"] = []
    else:
        text = _clip_str(remaining, _GAP_MAX)
        out["remaining_gaps"] = [text] if text else []

    out["distance_from_goal"] = _normalize_distance(out.get("distance_from_goal"))
    out["gap_reasoning"] = _clip_str(out.get("gap_reasoning", ""), _REASONING_MAX)
    if not out["gap_reasoning"]:
        out["gap_reasoning"] = out["evidence_summary"]
    return out


__all__ = [
    "coerce_goal_component_status_dict",
    "coerce_plan_gap_analysis_wire_dict",
]
