"""Tests for workspace CLAUDE.md / AGENTS.md WORKSPACE_INSTRUCTIONS loading."""

from __future__ import annotations

from pathlib import Path

import pytest

from soothe.core.loop.state.schemas import LoopState
from soothe.core.prompts import PromptBuilder


def test_load_workspace_project_instructions_reads_first_500_lines(tmp_path: Path) -> None:
    from soothe.core.prompts.project_instructions import load_workspace_project_instructions

    claude = tmp_path / "CLAUDE.md"
    claude.write_text("\n".join(f"claude line {i}" for i in range(600)), encoding="utf-8")
    agents = tmp_path / "AGENTS.md"
    agents.write_text("agents rule one\nagents rule two\n", encoding="utf-8")

    block = load_workspace_project_instructions(tmp_path, max_lines=500)
    assert block is not None
    assert "<WORKSPACE_INSTRUCTIONS>" in block
    # AGENTS.md is preferred, so CLAUDE.md content should NOT appear
    assert "claude line 0" not in block
    assert "agents rule one" in block
    assert "agents rule two" in block
    assert 'truncated="false"' in block


def test_load_workspace_project_instructions_claude_fallback(tmp_path: Path) -> None:
    """CLAUDE.md is fallback when no AGENTS.md found."""
    from soothe.core.prompts.project_instructions import load_workspace_project_instructions

    claude = tmp_path / "CLAUDE.md"
    claude.write_text("\n".join(f"claude line {i}" for i in range(600)), encoding="utf-8")

    block = load_workspace_project_instructions(tmp_path, max_lines=500)
    assert block is not None
    assert "<WORKSPACE_INSTRUCTIONS>" in block
    assert "claude line 0" in block
    assert "claude line 499" in block
    assert "claude line 500" not in block
    assert 'truncated="true"' in block


def test_load_workspace_project_instructions_agents_from_soothe_dir(tmp_path: Path) -> None:
    from soothe.core.prompts.project_instructions import load_workspace_project_instructions

    soothe = tmp_path / ".soothe"
    soothe.mkdir()
    (soothe / "AGENTS.md").write_text("from dot soothe\n", encoding="utf-8")

    block = load_workspace_project_instructions(tmp_path)
    assert block is not None
    assert "from dot soothe" in block
    assert ".soothe/AGENTS.md" in block


def test_envelope_functions_do_not_embed_project_instructions() -> None:
    """Envelope builders no longer embed project_instructions (moved to system prompt)."""
    from soothe.core.prompts.user_envelope import (
        build_execute_step_envelope,
        build_plan_context_envelope,
    )

    # Envelope functions don't have project_instructions parameter anymore
    execute = build_execute_step_envelope(
        "step",
        execution_hints="hint text",
    )
    plan = build_plan_context_envelope(
        goal="g",
    )
    assert "<USER_QUERY>" in execute
    assert "<USER_QUERY>" in plan
    assert "<CONTEXT_INFO>" in execute
    assert "<CONTEXT_INFO>" in plan


def test_plan_generate_context_without_project_instructions(tmp_path: Path) -> None:
    """Plan generate uses WORKSPACE_INSTRUCTIONS in system prompt, not envelope."""
    from soothe.protocols.planner import PlanContext

    (tmp_path / "CLAUDE.md").write_text("Plan must follow CLAUDE rules\n", encoding="utf-8")
    state = LoopState(goal="plan me", thread_id="t1", max_iterations=5, workspace=str(tmp_path))
    ctx = PlanContext(workspace=str(tmp_path))
    builder = PromptBuilder()
    assess = builder.build_plan_messages("plan me", state, ctx, plan_phase="assess")
    generate = builder.build_plan_messages("plan me", state, ctx, plan_phase="generate")

    assess_human = assess[-1].content
    generate_human = generate[-1].content
    # No project_instructions in envelope - it's in system prompt
    assert "<WORKSPACE_INSTRUCTIONS>" not in assess_human
    assert "<WORKSPACE_INSTRUCTIONS>" not in generate_human


@pytest.mark.asyncio
async def test_executor_envelope_without_project_instructions(tmp_path: Path) -> None:
    """Executor envelope no longer embeds project_instructions (moved to system prompt)."""
    from unittest.mock import MagicMock

    from soothe.core.loop.engine.executor import Executor
    from soothe.core.loop.state.schemas import StepAction

    (tmp_path / "AGENTS.md").write_text("execute agents guidance\n", encoding="utf-8")
    state = LoopState(goal="g", thread_id="t1", max_iterations=5, workspace=str(tmp_path))
    state.iteration = 2
    executor = Executor(MagicMock())
    steps = [
        StepAction(id="01", description="a", expected_output="o"),
        StepAction(id="02", description="b", expected_output="o"),
    ]

    messages = await executor._build_batch_human_messages(steps, state)
    assert len(messages) == 2
    # No project_instructions in envelope - it's in system prompt
    assert "<WORKSPACE_INSTRUCTIONS>" not in messages[0].content
    assert "<WORKSPACE_INSTRUCTIONS>" not in messages[1].content
