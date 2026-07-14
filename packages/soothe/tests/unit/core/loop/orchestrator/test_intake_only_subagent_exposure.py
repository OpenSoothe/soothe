"""IG-651: intake-only wire subagents vs open task catalog."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from langchain_core.messages import ToolMessage

from soothe.foundation.sloop.state.schemas import (
    INTAKE_ONLY_WIRE_SUBAGENTS,
    filter_task_catalog_subagent_names,
    is_intake_only_wire_subagent,
    partition_subagent_specs,
    resolve_step_wire_subagent,
    resolve_wire_subagent,
)
from soothe.middleware.tool_enforcement import ToolEnforcementMiddleware


def test_intake_only_set_excludes_planner() -> None:
    assert "planner" not in INTAKE_ONLY_WIRE_SUBAGENTS
    assert is_intake_only_wire_subagent("deep_research")
    assert is_intake_only_wire_subagent("browser_use")
    assert is_intake_only_wire_subagent("academic_research")
    assert not is_intake_only_wire_subagent("planner")


def test_filter_task_catalog_keeps_planner() -> None:
    names = [
        "planner",
        "deep_research",
        "browser_use",
        "academic_research",
        "plugin_agent",
    ]
    assert filter_task_catalog_subagent_names(names) == ["planner", "plugin_agent"]


def test_partition_subagent_specs_splits_intake_only() -> None:
    specs = [
        {"name": "planner", "description": "p"},
        {"name": "deep_research", "description": "d"},
        {"name": "plugin_agent", "description": "x"},
        {"name": "browser_use", "description": "b"},
    ]
    catalog, intake = partition_subagent_specs(specs)
    assert [s["name"] for s in catalog] == ["planner", "plugin_agent"]
    assert [s["name"] for s in intake] == ["deep_research", "browser_use"]


def test_wired_intake_still_resolves_all_four() -> None:
    assert resolve_wire_subagent(wire_subagent="planner") == "planner"
    assert resolve_wire_subagent(wire_subagent="deep_research") == "deep_research"
    assert resolve_wire_subagent(wire_subagent="academic_research") == "academic_research"


def test_plan_delegate_rejects_intake_only() -> None:
    assert resolve_step_wire_subagent(execution_hint="subagent", subagent="deep_research") is None
    assert resolve_step_wire_subagent(execution_hint="subagent", subagent="planner") == "planner"


@pytest.mark.asyncio
async def test_tool_enforcement_always_blocks_intake_only_task() -> None:
    mw = ToolEnforcementMiddleware()
    request = SimpleNamespace(
        tool_call={
            "name": "task",
            "id": "call-1",
            "args": {"description": "research X", "subagent_type": "deep_research"},
        },
        runtime=SimpleNamespace(state={"_subagent_routing_directive": "deep_research"}),
    )
    handler = AsyncMock(return_value="ok")
    result = await mw.awrap_tool_call(request, handler)  # type: ignore[arg-type]
    handler.assert_not_awaited()
    assert isinstance(result, ToolMessage)
    assert result.status == "error"
    assert "intake-only" in result.content
