"""Host intake-only vs open-task subagent catalog (StrangeLoop wiring).

Specialists in ``INTAKE_ONLY_WIRE_SUBAGENTS`` stay off the open ``task`` tool
catalog and are invoked via intake Pass 2 / slash wired routing.
"""

from __future__ import annotations

from typing import Any

# Specialists reachable only via host intake wiring — not the open task catalog.
# ``planner`` is intentionally excluded — it stays in the open task catalog.
INTAKE_ONLY_WIRE_SUBAGENTS = frozenset(
    {
        "explorer",
        "browser_use",
        "deep_research",
        "academic_research",
    }
)


def is_intake_only_wire_subagent(name: str | None) -> bool:
    """True when ``name`` is an intake-only specialist (not open task catalog)."""
    token = (name or "").strip()
    return bool(token) and token in INTAKE_ONLY_WIRE_SUBAGENTS


def filter_task_catalog_subagent_names(names: list[str] | tuple[str, ...] | set[str]) -> list[str]:
    """Drop intake-only specialists from open CoreAgent / planner capability lists."""
    return [n for n in names if n and not is_intake_only_wire_subagent(n)]


def spec_subagent_name(spec: Any) -> str | None:
    """Best-effort name from a SubAgent / CompiledSubAgent dict or object."""
    if isinstance(spec, dict):
        raw = spec.get("name")
        return raw.strip() if isinstance(raw, str) and raw.strip() else None
    raw_name = getattr(spec, "name", None)
    if isinstance(raw_name, str) and raw_name.strip():
        return raw_name.strip()
    return None


def partition_subagent_specs(specs: list[Any]) -> tuple[list[Any], list[Any]]:
    """Split specs into (task-catalog, intake-only) lists."""
    catalog: list[Any] = []
    intake_only: list[Any] = []
    for spec in specs:
        name = spec_subagent_name(spec)
        if is_intake_only_wire_subagent(name):
            intake_only.append(spec)
        else:
            catalog.append(spec)
    return catalog, intake_only


def lookup_subagent_spec(specs: list[Any], name: str) -> Any | None:
    """Return the first subagent spec whose name matches ``name``."""
    target = (name or "").strip()
    if not target:
        return None
    for spec in specs:
        if spec_subagent_name(spec) == target:
            return spec
    return None


__all__ = [
    "INTAKE_ONLY_WIRE_SUBAGENTS",
    "filter_task_catalog_subagent_names",
    "is_intake_only_wire_subagent",
    "lookup_subagent_spec",
    "partition_subagent_specs",
    "spec_subagent_name",
]
