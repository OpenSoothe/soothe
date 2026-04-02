"""Reason-phase prompt includes workspace context (Layer 2, RFC-104)."""

from __future__ import annotations

from unittest.mock import MagicMock

from soothe.backends.planning.simple import build_loop_reason_prompt
from soothe.cognition.loop_agent.schemas import LoopState
from soothe.protocols.planner import PlanContext


def test_build_loop_reason_prompt_with_config_includes_soothe_blocks() -> None:
    state = LoopState(goal="analyze architecture", thread_id="t1", max_iterations=8)
    ctx = PlanContext(workspace="/abs/path/to/repo")
    config = MagicMock()
    config.resolve_model.return_value = "claude-opus-4-6"
    text = build_loop_reason_prompt("analyze architecture", state, ctx, config=config)
    assert "<SOOTHE_ENVIRONMENT" in text
    assert "<SOOTHE_WORKSPACE" in text
    assert "/abs/path/to/repo" in text
    assert "<SOOTHE_REASON_WORKSPACE_RULES>" in text
    assert "Do NOT ask the user" in text


def test_build_loop_reason_prompt_without_config_workspace_only() -> None:
    state = LoopState(goal="analyze architecture", thread_id="t1", max_iterations=8)
    ctx = PlanContext(workspace="/abs/path/to/repo")
    text = build_loop_reason_prompt("analyze architecture", state, ctx)
    assert "<SOOTHE_ENVIRONMENT" not in text
    assert "<SOOTHE_WORKSPACE" in text
    assert "/abs/path/to/repo" in text
    assert "<SOOTHE_REASON_WORKSPACE_RULES>" in text


def test_build_loop_reason_prompt_omits_workspace_rules_without_workspace() -> None:
    state = LoopState(goal="hi", thread_id="t1", max_iterations=8)
    ctx = PlanContext(workspace=None)
    text = build_loop_reason_prompt("hi", state, ctx)
    assert "<SOOTHE_REASON_WORKSPACE_RULES>" not in text
