"""Wire coercion for PlanGapAnalysis structured LLM output.

Models sometimes emit ``name`` (or similar) instead of the schema field
``component`` on ``components[]`` items. Coerce before jsonschema validation
so a single alias slip cannot abort the StrangeLoop graph.
"""

from __future__ import annotations

from typing import Any

# Alias keys models use for GoalComponentStatus.component (first wins).
_COMPONENT_ALIASES: tuple[str, ...] = ("name", "title", "label")


def coerce_goal_component_status_dict(data: Any) -> Any:
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
    if not isinstance(components, list):
        return out

    out["components"] = [coerce_goal_component_status_dict(item) for item in components]
    return out


__all__ = [
    "coerce_goal_component_status_dict",
    "coerce_plan_gap_analysis_wire_dict",
]
