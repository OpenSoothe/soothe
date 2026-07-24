"""Tests for AGENTS.md / CLAUDE.md AGENT_INSTRUCTIONS loading."""

from __future__ import annotations

from pathlib import Path

import pytest

from soothe.prompts import PromptBuilder
from soothe.sloop.state.schemas import LoopState


def test_headline_max_chars_caps_inlined_body(tmp_path: Path) -> None:
    from soothe.prompts.project_instructions import (
        load_agent_instructions,
    )

    agents = tmp_path / "AGENTS.md"
    agents.write_text("A" * 20_000, encoding="utf-8")
    block = load_agent_instructions(tmp_path, headline_max_chars=8000)
    assert block is not None
    assert len(block) < 20_000
    assert "<NOTE>" in block or 'inlined="partial"' in block


def test_load_agent_instructions_reads_first_500_lines(tmp_path: Path) -> None:
    from soothe.prompts.project_instructions import (
        load_agent_instructions,
    )

    claude = tmp_path / "CLAUDE.md"
    claude.write_text("\n".join(f"claude line {i}" for i in range(600)), encoding="utf-8")
    agents = tmp_path / "AGENTS.md"
    agents.write_text("agents rule one\nagents rule two\n", encoding="utf-8")

    block = load_agent_instructions(tmp_path, max_lines=500)
    assert block is not None
    assert "<AGENT_INSTRUCTIONS>" in block
    # AGENTS.md is preferred, so CLAUDE.md content should NOT appear
    assert "claude line 0" not in block
    assert "agents rule one" in block
    assert "agents rule two" in block
    # Small AGENTS.md inlines fully; no read_file note.
    assert 'inlined="full"' in block
    assert 'truncated_lines="false"' in block
    assert "<NOTE>" not in block


def test_load_agent_instructions_claude_fallback(tmp_path: Path) -> None:
    """CLAUDE.md fallback: 600 lines fits under 25K headline cap but trips line cap."""
    from soothe.prompts.project_instructions import (
        load_agent_instructions,
    )

    claude = tmp_path / "CLAUDE.md"
    # 600 lines of `claude line N\n` is ~7.5 KB — well under the 25K headline cap,
    # so the body inlines fully. The 500-line cap still drops lines 500..599 and
    # marks ``truncated_lines=true``, which alone is enough to emit the note.
    claude.write_text("\n".join(f"claude line {i}" for i in range(600)), encoding="utf-8")

    block = load_agent_instructions(tmp_path, max_lines=500)
    assert block is not None
    assert "<AGENT_INSTRUCTIONS>" in block
    assert "claude line 0" in block
    # First 500 lines inline verbatim; lines past the line cap stay out.
    assert "claude line 499" in block
    assert "claude line 500" not in block
    assert 'inlined="full"' in block
    assert 'truncated_lines="true"' in block
    # Line-cap truncation still emits the read_file hint.
    assert "<NOTE>" in block
    assert "read_file" in block
    assert str(claude) in block


def test_load_agent_instructions_agents_from_soothe_dir(tmp_path: Path) -> None:
    from soothe.prompts.project_instructions import (
        load_agent_instructions,
    )

    soothe = tmp_path / ".soothe"
    soothe.mkdir()
    (soothe / "AGENTS.md").write_text("from dot soothe\n", encoding="utf-8")

    block = load_agent_instructions(tmp_path)
    assert block is not None
    assert "from dot soothe" in block
    assert ".soothe/AGENTS.md" in block


def test_envelope_functions_do_not_embed_project_instructions() -> None:
    """Envelope builders no longer embed project_instructions (moved to system prompt)."""
    from soothe.prompts.user_message import UserMessageBuilder

    # Envelope functions don't have project_instructions parameter anymore
    builder = UserMessageBuilder()
    execute = builder.build_execute_step_message(
        "step",
        instructions="hint text",
    )
    plan = builder.build_plan_assess_message(
        goal="g",
    )
    assert "EXECUTION TASK:" in execute
    assert "GOAL:" in plan
    assert "TIMESTAMP:" not in execute
    assert "TIMESTAMP:" not in plan


def test_plan_generate_context_without_project_instructions(tmp_path: Path) -> None:
    """plan-generate omits AGENT_INSTRUCTIONS in system and human messages."""
    from soothe_sdk.protocols.planner import PlanContext

    (tmp_path / "CLAUDE.md").write_text("Plan must follow CLAUDE rules\n", encoding="utf-8")
    state = LoopState(goal="plan me", thread_id="t1", max_iterations=5, workspace=str(tmp_path))
    ctx = PlanContext(workspace=str(tmp_path))
    builder = PromptBuilder()
    assess = builder.build_plan_messages("plan me", state, ctx, plan_phase="assess")
    generate = builder.build_plan_messages("plan me", state, ctx, plan_phase="generate")

    assess_human = assess[-1].content
    generate_human = generate[-1].content
    generate_system = generate[0].content
    assert "<AGENT_INSTRUCTIONS>" not in assess_human
    assert "<AGENT_INSTRUCTIONS>" not in generate_human
    assert "<AGENT_INSTRUCTIONS>" not in generate_system
    assert "Plan must follow CLAUDE rules" not in generate_system


@pytest.mark.asyncio
async def test_executor_envelope_without_project_instructions(tmp_path: Path) -> None:
    """Executor envelope no longer embeds project_instructions (moved to system prompt)."""
    from unittest.mock import MagicMock

    from soothe.sloop.engine.executor import Executor
    from soothe.sloop.state.schemas import StepAction

    (tmp_path / "AGENTS.md").write_text("execute agents guidance\n", encoding="utf-8")
    state = LoopState(goal="g", thread_id="t1", max_iterations=5, workspace=str(tmp_path))
    state.iteration = 2
    executor = Executor(MagicMock())
    steps = [
        StepAction(id="01", description="a", expected_output="o"),
        StepAction(id="02", description="b", expected_output="o"),
    ]

    envelopes = [
        executor._compose_execute_step_envelope(
            step,
            loop_state=state,
            wire_subagent=None,
            workspace=state.workspace,
        )
        for step in steps
    ]
    assert len(envelopes) == 2
    # No project_instructions in envelope - it's in system prompt
    assert "<AGENT_INSTRUCTIONS>" not in envelopes[0]
    assert "<AGENT_INSTRUCTIONS>" not in envelopes[1]


def test_inlines_small_agents_md_fully(tmp_path: Path) -> None:
    """Files under the headline cap inline verbatim with no read_file hint."""
    from soothe.prompts.project_instructions import (
        PROJECT_INSTRUCTION_HEADLINE_MAX_CHARS,
        load_agent_instructions,
    )

    body = "# Project Rules\n\nBe terse.\n"
    assert len(body) <= PROJECT_INSTRUCTION_HEADLINE_MAX_CHARS
    (tmp_path / "AGENTS.md").write_text(body, encoding="utf-8")

    block = load_agent_instructions(tmp_path)
    assert block is not None
    assert "Be terse." in block
    assert 'inlined="full"' in block
    assert "<NOTE>" not in block


def test_progressive_partial_above_threshold(tmp_path: Path) -> None:
    """Files above the headline cap emit a paragraph-clean prefix + read_file hint."""
    from soothe.prompts.project_instructions import (
        PROJECT_INSTRUCTION_HEADLINE_MAX_CHARS,
        load_agent_instructions,
    )

    # Build a body that exceeds the 25K headline cap with clear paragraph
    # boundaries so the truncator backs off to a "\n\n" cut rather than
    # mid-sentence. 200 paragraphs × ~194 chars ≈ 39 KB; line count stays
    # under the 500-line cap (200 paragraphs + 199 blanks = 399 lines).
    paragraphs = [f"Paragraph {i}: " + ("rule. " * 30) for i in range(200)]
    body = "\n\n".join(paragraphs) + "\n"
    assert len(body) > PROJECT_INSTRUCTION_HEADLINE_MAX_CHARS
    agents = tmp_path / "AGENTS.md"
    agents.write_text(body, encoding="utf-8")

    block = load_agent_instructions(tmp_path)
    assert block is not None
    assert 'inlined="partial"' in block
    assert "<NOTE>" in block
    assert f'read_file("{agents}")' in block
    # CDATA payload should be smaller than the body and end on a paragraph
    # boundary (the last visible char before `]]>` is not mid-sentence).
    cdata_start = block.index("<![CDATA[") + len("<![CDATA[\n")
    cdata_end = block.index("\n]]>")
    payload = block[cdata_start:cdata_end]
    assert len(payload) <= PROJECT_INSTRUCTION_HEADLINE_MAX_CHARS
    assert payload.rstrip().endswith(".")


def test_lru_cache_hits_on_unchanged_file(tmp_path: Path) -> None:
    """Second load with unchanged mtime hits the cache; no second disk read."""
    from soothe.prompts import project_instructions
    from soothe.prompts.project_instructions import (
        load_agent_instructions,
    )

    (tmp_path / "AGENTS.md").write_text("rule\n", encoding="utf-8")
    # Reset the LRU cache so neighboring tests don't pollute hit/miss counts.
    project_instructions.build_block_cached.cache_clear()

    first = load_agent_instructions(tmp_path)
    after_first = project_instructions.build_block_cached.cache_info()
    second = load_agent_instructions(tmp_path)
    after_second = project_instructions.build_block_cached.cache_info()

    assert first is not None
    assert first == second
    assert after_first.misses == 1
    assert after_second.hits >= 1
    assert after_second.misses == after_first.misses


def test_lru_cache_invalidates_on_mtime_change(tmp_path: Path) -> None:
    """Editing the file (advancing mtime) returns updated content on next load."""
    import os

    from soothe.prompts import project_instructions
    from soothe.prompts.project_instructions import (
        load_agent_instructions,
    )

    agents = tmp_path / "AGENTS.md"
    agents.write_text("original rule\n", encoding="utf-8")
    project_instructions.build_block_cached.cache_clear()

    first = load_agent_instructions(tmp_path)
    assert first is not None
    assert "original rule" in first

    # Rewrite with new content and advance mtime past the original.
    agents.write_text("updated rule\n", encoding="utf-8")
    new_mtime_ns = agents.stat().st_mtime_ns + 1_000_000_000  # +1s
    os.utime(agents, ns=(new_mtime_ns, new_mtime_ns))

    second = load_agent_instructions(tmp_path)
    assert second is not None
    assert "updated rule" in second
    assert "original rule" not in second
