"""Tests for workspace CLAUDE.md / AGENTS.md CONTEXT_INFO loading."""

from __future__ import annotations

from pathlib import Path

import pytest

from soothe.core.prompts.project_instructions import load_workspace_project_instructions
from soothe.core.prompts.user_envelope import (
    build_execute_step_envelope,
    build_plan_context_envelope,
)


def test_load_workspace_project_instructions_reads_first_500_lines(tmp_path: Path) -> None:
    claude = tmp_path / "CLAUDE.md"
    claude.write_text("\n".join(f"claude line {i}" for i in range(600)), encoding="utf-8")
    agents = tmp_path / "AGENTS.md"
    agents.write_text("agents rule one\nagents rule two\n", encoding="utf-8")

    block = load_workspace_project_instructions(tmp_path, max_lines=500)
    assert block is not None
    assert "<project_instructions>" in block
    assert "claude line 0" in block
    assert "claude line 499" in block
    assert "claude line 500" not in block
    assert 'truncated="true"' in block
    assert "agents rule one" in block
    assert 'truncated="false"' in block


def test_load_workspace_project_instructions_agents_from_soothe_dir(tmp_path: Path) -> None:
    soothe = tmp_path / ".soothe"
    soothe.mkdir()
    (soothe / "AGENTS.md").write_text("from dot soothe\n", encoding="utf-8")

    block = load_workspace_project_instructions(tmp_path)
    assert block is not None
    assert "from dot soothe" in block
    assert ".soothe/AGENTS.md" in block


def test_envelopes_embed_project_instructions_in_context_info() -> None:
    snippet = (
        "<project_instructions>\n"
        '<file name="CLAUDE.md" truncated="false">\n'
        "<![CDATA[\nrule\n]]>\n"
        "</file>\n"
        "</project_instructions>"
    )
    execute = build_execute_step_envelope(
        goal="g",
        step_description="step",
        project_instructions=snippet,
    )
    plan = build_plan_context_envelope(
        goal="g",
        iteration=1,
        max_iterations=3,
        project_instructions=snippet,
    )
    assert snippet in execute
    assert execute.index("<CONTEXT_INFO>") < execute.index("<project_instructions>")
    assert snippet in plan
    assert plan.index("<CONTEXT_INFO>") < plan.index("<project_instructions>")


def test_plan_generate_includes_project_instructions(tmp_path: Path) -> None:
    from soothe.core.prompts.builder import PromptBuilder
    from soothe.core.loop.state.schemas import LoopState
    from soothe.protocols.planner import PlanContext

    (tmp_path / "CLAUDE.md").write_text("Plan must follow CLAUDE rules\n", encoding="utf-8")
    state = LoopState(goal="plan me", thread_id="t1", max_iterations=5, workspace=str(tmp_path))
    ctx = PlanContext(workspace=str(tmp_path))
    builder = PromptBuilder()
    assess = builder.build_plan_messages("plan me", state, ctx, plan_phase="assess")
    generate = builder.build_plan_messages("plan me", state, ctx, plan_phase="generate")

    assess_human = assess[-1].content
    generate_human = generate[-1].content
    assert "<project_instructions>" not in assess_human
    assert "<project_instructions>" in generate_human
    assert "Plan must follow CLAUDE rules" in generate_human


@pytest.mark.asyncio
async def test_executor_claims_project_instructions_once_per_iteration(
    tmp_path: Path,
) -> None:
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
    assert "<project_instructions>" in messages[0].content
    assert "<project_instructions>" not in messages[1].content
    assert state.project_instructions_execute_iteration == 2

    state.iteration = 3
    messages_again = await executor._build_batch_human_messages(steps, state)
    assert "<project_instructions>" in messages_again[0].content
    assert state.project_instructions_execute_iteration == 3
