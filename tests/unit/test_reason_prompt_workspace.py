"""Reason-phase prompt includes working directory (Layer 2)."""

from __future__ import annotations

from soothe.backends.planning.simple import build_loop_reason_prompt
from soothe.cognition.loop_agent.schemas import LoopState
from soothe.protocols.planner import PlanContext


def test_build_loop_reason_prompt_includes_working_directory() -> None:
    state = LoopState(goal="analyze architecture", thread_id="t1", max_iterations=8)
    ctx = PlanContext(workspace="/abs/path/to/repo")
    text = build_loop_reason_prompt("analyze architecture", state, ctx)
    assert "/abs/path/to/repo" in text
    assert "<WORKING_DIRECTORY>" in text
    assert "Do NOT ask the user" in text


def test_build_loop_reason_prompt_omits_block_without_workspace() -> None:
    state = LoopState(goal="hi", thread_id="t1", max_iterations=8)
    ctx = PlanContext(workspace=None)
    text = build_loop_reason_prompt("hi", state, ctx)
    assert "<WORKING_DIRECTORY>" not in text
