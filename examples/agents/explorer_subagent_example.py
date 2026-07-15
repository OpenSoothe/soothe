"""Example: explorer wired subagent configuration and routing check.

This lightweight example validates that the built-in `explorer` subagent is:
- enabled in config
- resolvable through Pass 2 wired routing
- kept in the open task catalog (not intake-only)

Run:
    python -m examples.agents.explorer_subagent_example
"""

from __future__ import annotations

from soothe.foundation.sloop.state.schemas import (
    filter_task_catalog_subagent_names,
    is_intake_only_wire_subagent,
    resolve_wire_subagent,
)

from examples._config_helper import load_example_config


def main() -> None:
    """Print and verify explorer subagent wiring state."""
    print("=" * 60)
    print("Example: explorer Subagent")
    print("=" * 60)

    config = load_example_config()
    explorer_cfg = config.subagents.get("explorer")
    if explorer_cfg is None or not explorer_cfg.enabled:
        raise RuntimeError("Explorer subagent is not enabled in config.")

    resolved = resolve_wire_subagent(wire_subagent="explorer")
    if resolved != "explorer":
        raise RuntimeError(f"Wire routing failed: expected 'explorer', got {resolved!r}")

    if is_intake_only_wire_subagent("explorer"):
        raise RuntimeError("Explorer must be task-catalog reachable, not intake-only.")

    catalog = filter_task_catalog_subagent_names(
        ["planner", "explorer", "browser_use", "deep_research"]
    )
    if "explorer" not in catalog:
        raise RuntimeError("Explorer not visible in task-catalog subagent list.")

    print("[Config] explorer: enabled")
    print("[Routing] wire_subagent='explorer' -> explorer")
    print("[Catalog] explorer remains available in task-catalog delegates")
    print("\nTry this user query:")
    print("  /explorer where retry middleware is implemented")
    print("\nVerification passed.")


if __name__ == "__main__":
    main()
