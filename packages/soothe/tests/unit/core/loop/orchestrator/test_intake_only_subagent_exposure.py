"""IG-600: intake-only wire subagents vs open task catalog."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from langchain_core.messages import ToolMessage

from soothe.sloop.intake_task_guard import IntakeOnlyTaskGuardMiddleware
from soothe.sloop.state.schemas import (
    INTAKE_ONLY_WIRE_SUBAGENTS,
    filter_task_catalog_subagent_names,
    is_intake_only_wire_subagent,
    partition_subagent_specs,
    resolve_step_wire_subagent,
    resolve_wire_subagent,
)


def test_intake_only_set_includes_planner() -> None:
    assert "planner" in INTAKE_ONLY_WIRE_SUBAGENTS
    assert "explorer" not in INTAKE_ONLY_WIRE_SUBAGENTS
    assert is_intake_only_wire_subagent("planner")
    assert is_intake_only_wire_subagent("deep_research")
    assert is_intake_only_wire_subagent("browser_use")
    assert is_intake_only_wire_subagent("academic_research")
    assert not is_intake_only_wire_subagent("explorer")


def test_filter_task_catalog_excludes_intake_only_subagents() -> None:
    names = [
        "planner",
        "deep_research",
        "browser_use",
        "academic_research",
        "plugin_agent",
    ]
    assert filter_task_catalog_subagent_names(names) == ["plugin_agent"]


def test_partition_subagent_specs_splits_intake_only() -> None:
    specs = [
        {"name": "planner", "description": "p"},
        {"name": "deep_research", "description": "d"},
        {"name": "plugin_agent", "description": "x"},
        {"name": "browser_use", "description": "b"},
    ]
    catalog, intake = partition_subagent_specs(specs)
    assert [s["name"] for s in catalog] == ["plugin_agent"]
    assert [s["name"] for s in intake] == ["planner", "deep_research", "browser_use"]


def test_wired_intake_still_resolves_all_supported_specialists() -> None:
    assert resolve_wire_subagent(wire_subagent="planner") == "planner"
    assert resolve_wire_subagent(wire_subagent="explorer") is None
    assert resolve_wire_subagent(wire_subagent="deep_research") == "deep_research"
    assert resolve_wire_subagent(wire_subagent="academic_research") == "academic_research"


def test_plan_delegate_rejects_intake_only() -> None:
    assert resolve_step_wire_subagent(execution_hint="subagent", subagent="deep_research") is None
    assert resolve_step_wire_subagent(execution_hint="subagent", subagent="planner") is None


@pytest.mark.asyncio
async def test_intake_task_guard_always_blocks_intake_only_task() -> None:
    mw = IntakeOnlyTaskGuardMiddleware()
    for name in ("deep_research", "planner", "browser_use", "academic_research"):
        request = SimpleNamespace(
            tool_call={
                "name": "task",
                "id": "call-1",
                "args": {"description": "do work", "subagent_type": name},
            },
            runtime=SimpleNamespace(state={"_subagent_routing_directive": name}),
        )
        handler = AsyncMock(return_value="ok")
        result = await mw.awrap_tool_call(request, handler)  # type: ignore[arg-type]
        handler.assert_not_awaited()
        assert isinstance(result, ToolMessage)
        assert result.status == "error"
        assert "not available via" in result.content
        assert "intake-only" in result.content
