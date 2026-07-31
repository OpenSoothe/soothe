"""StrangeLoop checkpoint key isolation + clarification resume branching."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from langgraph.types import Command

from soothe.sloop.clarification.origins import ORIGIN_PLANNER_SUBAGENT_REVIEW
from soothe.sloop.orchestrator.checkpoint_keys import (
    intake_only_invoke_config,
    snapshot_has_resumable_interrupt,
    strange_loop_configurable,
    strange_loop_thread_id,
)
from soothe.sloop.orchestrator.runner import (
    _clarification_resume_command,
    build_loop_graph_invoke_config,
)
from soothe.sloop.orchestrator.stations import DELEGATE


def test_strange_loop_configurable_sets_isolated_thread() -> None:
    conf = strange_loop_configurable("loop-1", workspace="/tmp/ws")
    assert conf["thread_id"] == strange_loop_thread_id("loop-1")
    assert "checkpoint_ns" not in conf
    assert conf["workspace"] == "/tmp/ws"


def test_intake_only_invoke_config_isolates_thread() -> None:
    cfg = intake_only_invoke_config("loop-1", "planner", workspace="/ws")
    conf = cfg["configurable"]
    assert conf["thread_id"] == "loop-1__intake__planner"
    assert "checkpoint_ns" not in conf
    assert conf["workspace"] == "/ws"


def test_build_loop_graph_invoke_config_sets_strange_loop_thread() -> None:
    from soothe.config import SootheConfig

    cfg = SootheConfig()
    cfg.observability.langfuse.enabled = False

    ctx = MagicMock()
    ctx.strange_loop = MagicMock(config=cfg)
    ctx.state_manager = MagicMock(loop_id="loop-abc")
    ctx.loop_state = MagicMock(thread_id="thread-xyz", workspace=None)
    ctx.goal_trace = None
    ctx.proposal_queue = None

    out = build_loop_graph_invoke_config(ctx)
    assert out["configurable"]["thread_id"] == strange_loop_thread_id("loop-abc")
    assert "checkpoint_ns" not in out["configurable"]


def test_snapshot_has_resumable_interrupt_from_top_level() -> None:
    snap = SimpleNamespace(interrupts=(object(),), tasks=())
    assert snapshot_has_resumable_interrupt(snap) is True


def test_snapshot_has_resumable_interrupt_from_tasks() -> None:
    task = SimpleNamespace(interrupts=(object(),))
    snap = SimpleNamespace(interrupts=(), tasks=(task,))
    assert snapshot_has_resumable_interrupt(snap) is True


def test_snapshot_has_resumable_interrupt_absent() -> None:
    snap = SimpleNamespace(interrupts=(), tasks=(SimpleNamespace(interrupts=()),))
    assert snapshot_has_resumable_interrupt(snap) is False


def test_clarification_resume_command_uses_resume_when_interrupt_live() -> None:
    snap = SimpleNamespace(
        interrupts=(object(),),
        tasks=(),
        values={"last_clarification_origin": ORIGIN_PLANNER_SUBAGENT_REVIEW},
    )
    cmd = _clarification_resume_command(
        snapshot=snap,
        resume_answers=["Approve", ""],
        loop_id="loop-1",
    )
    assert isinstance(cmd, Command)
    assert cmd.resume == {"answers": ["Approve", ""]}
    assert cmd.goto == ()


def test_clarification_resume_command_goto_recovery_when_interrupt_orphaned() -> None:
    snap = SimpleNamespace(
        interrupts=(),
        tasks=(),
        values={"last_clarification_origin": ORIGIN_PLANNER_SUBAGENT_REVIEW},
    )
    cmd = _clarification_resume_command(
        snapshot=snap,
        resume_answers=["Approve", ""],
        loop_id="loop-1",
    )
    assert isinstance(cmd, Command)
    assert cmd.resume is None
    assert cmd.goto == DELEGATE
    update = cmd.update
    assert isinstance(update, dict)
    answer = update.get("pending_clarification_answer")
    assert isinstance(answer, dict)
    assert answer.get("answers") == ["Approve", ""]
    assert answer.get("source") == "human"


@pytest.mark.asyncio
async def test_run_intake_only_passes_isolated_config() -> None:
    from unittest.mock import AsyncMock, patch

    from soothe.sloop.stages.sidecars.delegate import _run_intake_only_runnable

    runnable = MagicMock()
    runnable.astream = MagicMock(side_effect=TypeError("no stream_mode"))
    runnable.ainvoke = AsyncMock(return_value={"messages": []})

    ctx = MagicMock()
    ctx.state_manager = MagicMock(loop_id="loop-9")
    ctx.loop_state = MagicMock(workspace="/ws")
    ctx.emit = AsyncMock()

    with (
        patch("soothe_nano.utils.progress.set_wire_bridge", return_value="tok"),
        patch("soothe_nano.utils.progress.reset_wire_bridge"),
    ):
        await _run_intake_only_runnable(
            ctx,
            runnable,
            goal_text="plan it",
            invocation_id="abc",
            step_id="S1",
            wire="planner",
        )

    runnable.ainvoke.assert_awaited_once()
    _args, kwargs = runnable.ainvoke.await_args
    conf = kwargs["config"]["configurable"]
    assert conf["thread_id"] == "loop-9__intake__planner"
    assert "checkpoint_ns" not in conf
