"""Step card nests subgraph tools under Explore/task delegation rows (IG-419)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from soothe_cli.tui.file_ops import FileOpTracker
from soothe_cli.tui.step_task_routing import StepTaskRouter
from soothe_cli.tui.textual_adapter import TextualUIAdapter
from soothe_cli.tui.textual_adapter._stream_formatting import (
    _mount_subagent_inner_tool_row_if_resolved,
    _should_append_subagent_wire_line_to_parent,
    _try_register_task_scoped_inner_tool_pending,
)
from soothe_cli.tui.widgets.messages import CognitionStepMessage


def test_resolve_parent_task_call_id_uses_task_scope() -> None:
    router = StepTaskRouter()
    ns = ("tools:explore-ns",)
    router.on_subgraph_namespace(ns)
    router.register_task_spawn("VKJ-01:s:task.0", "explore", step_id="VKJ-01")
    assert (
        router.resolve_parent_task_call_id(ns, inner_tool_call_id="VKJ-01:t0:glob.1")
        == "VKJ-01:s:task.0"
    )


def test_step_card_keeps_full_description() -> None:
    long_desc = "Explore project root directory structure to identify top-level organization " * 3
    w = CognitionStepMessage("s1", long_desc, id="st-nest-desc")
    assert w._description == long_desc.strip()  # noqa: SLF001


def test_should_skip_tool_wire_echo_on_step_card() -> None:
    step = CognitionStepMessage("s1", "Work", id="st-wire")
    assert (
        _should_append_subagent_wire_line_to_parent(
            step, event_type="soothe.subagent.explore.step_completed"
        )
        is False
    )
    assert (
        _should_append_subagent_wire_line_to_parent(
            step, event_type="soothe.subagent.explore.milestone"
        )
        is True
    )


@pytest.mark.asyncio
async def test_inner_tool_row_nested_under_task_on_step_card() -> None:
    adapter = TextualUIAdapter(
        mount_message=AsyncMock(),
        update_status=MagicMock(),
        request_approval=AsyncMock(),
        set_spinner=AsyncMock(),
    )
    router = adapter._step_router
    step = CognitionStepMessage(
        "VKJ-01",
        "Explore project root directory structure",
        id="st-nest",
    )
    adapter._current_step_messages["VKJ-01"] = step
    step.add_tool_call(
        "VKJ-01:s:task.0",
        "explore",
        {"subagent_type": "explore", "description": "Explore project root"},
        is_task_row=True,
    )
    ns = ("tools:sub",)
    router.on_subgraph_namespace(ns)
    router.register_task_spawn("VKJ-01:s:task.0", "explore", step_id="VKJ-01")

    ok = await _mount_subagent_inner_tool_row_if_resolved(
        adapter,
        router,
        lookup_id="VKJ-01:t0:glob.1",
        buffer_name="glob",
        parsed_args={"glob_pattern": "**/*"},
        buffer_id="VKJ-01:t0:glob.1",
        ns_key=ns,
        show_tool_ui=True,
        is_main_agent=False,
        pending_tool_calls_lc={},
        file_op_tracker=FileOpTracker(assistant_id="a"),
    )
    assert ok is True
    child = step._row_index["VKJ-01:t0:glob.1"]  # noqa: SLF001
    assert child.parent_tool_call_id == "VKJ-01:s:task.0"


def test_task_row_shows_subagent_name_and_truncated_description() -> None:
    from soothe_cli.tui.preview_limits import STEP_TASK_DELEGATION_DESC_MAX_CHARS
    from soothe_cli.tui.tool_display import format_task_delegation_cli_command

    long_desc = (
        "Explore top-level project structure and identify main directories, "
        "README, and config files to understand project dependencies and build configuration"
    )
    line = format_task_delegation_cli_command(
        "explore",
        {"subagent_type": "explore", "description": long_desc},
    )
    assert "Explore(" in line
    assert ", explore" not in line
    assert len(long_desc) > STEP_TASK_DELEGATION_DESC_MAX_CHARS
    assert long_desc not in line
    assert "…" in line or "..." in line


def test_no_pending_text_line_when_step_card_has_tool_rows() -> None:
    adapter = TextualUIAdapter(
        mount_message=AsyncMock(),
        update_status=MagicMock(),
        request_approval=AsyncMock(),
    )
    router = adapter._step_router
    step = CognitionStepMessage("VKJ-01", "Work", id="st-pend")
    adapter._current_step_messages["VKJ-01"] = step
    ns = ("tools:sub",)
    router.on_subgraph_namespace(ns)
    router.register_task_spawn("VKJ-01:s:task.0", "explore", step_id="VKJ-01")

    presentation = MagicMock()
    presentation.tier_visible.return_value = True

    _try_register_task_scoped_inner_tool_pending(
        adapter,
        router,
        lookup_id="VKJ-01:t0:ls.0",
        buffer_name="ls",
        parsed_args={"path": "."},
        is_main_agent=False,
        ns_key=ns,
        show_tool_ui=True,
        presentation=presentation,
    )
    assert adapter._task_inner_tool_pending_lines == {}
