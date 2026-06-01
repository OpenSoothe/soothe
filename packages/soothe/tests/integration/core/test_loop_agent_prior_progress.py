"""Integration: executor produces digest, plan-builder threads it to assess prompt.

Replays the "count file types" scenario from the motivating trace
(279a91c70f73f5b71fb31a5b61370f45): after a wave of ``run_command`` results,
the next plan-assess prompt MUST carry concrete evidence the LLM can cite.
"""

from __future__ import annotations

from langchain_core.messages import AIMessage, ToolMessage

from soothe.core.loop.engine.executor import Executor
from soothe.core.loop.state.schemas import (
    LoopState,
    StepAction,
    StepResult,
)
from soothe.core.prompts import PromptBuilder
from soothe.protocols.planner import PlanContext


def _ok_step(step_id: str, ai_text: str, tool_name: str, tool_body: str) -> tuple:
    return (
        [],
        StepResult(
            step_id=step_id,
            success=True,
            outcome={"type": "code_exec"},
            duration_ms=12,
            thread_id="t1",
            tool_call_count=1,
        ),
        [
            ToolMessage(content=tool_body, tool_call_id=f"call_{step_id}", name=tool_name),
            AIMessage(content=ai_text),
        ],
        "",
    )


def test_count_file_types_replay_assess_prompt_carries_evidence() -> None:
    """After 3 successful run_command waves for file-count steps, the next
    plan-assess prompt must contain <PRIOR_PROGRESS> with tool names and an
    evidence excerpt the LLM can cite — no more goal restatement.
    """
    state = LoopState(
        goal="count all file types of the project",
        thread_id="t1",
        iteration=1,  # the failure mode hit on iteration 1+ in the trace
    )
    ex = Executor(object(), max_parallel_steps=4)

    steps = [
        StepAction(id="s1", description="count .py files", expected_output="n"),
        StepAction(id="s2", description="count .json files", expected_output="n"),
        StepAction(id="s3", description="count .md files", expected_output="n"),
    ]
    wave_results = [
        _ok_step("s1", "Counted .py: 1139", "run_command", "1139"),
        _ok_step("s2", "Counted .json: 665", "run_command", "665"),
        _ok_step("s3", "Counted .md: 217", "run_command", "217"),
    ]

    ex._append_parallel_wave_ledger(state, steps, wave_results)

    # Producer side: digest carries the truth.
    digest = state.prior_progress
    assert digest is not None
    assert digest.steps_completed == 3
    assert digest.steps_failed == 0
    assert digest.derived_progress_hint == "high"
    assert any(t.name == "run_command" for t in digest.tool_calls)
    assert any("1139" in e for e in digest.evidence_excerpts)

    # Move to iteration 2 (next plan-assess sees the prior wave as fresh).
    state.iteration = 2

    builder = PromptBuilder()
    msgs = builder.build_plan_messages(
        "count all file types of the project", state, PlanContext(), plan_phase="assess"
    )
    assess_human = msgs[-1].content
    assert "<PRIOR_PROGRESS>" in assess_human
    # The block names the tool and embeds at least one evidence excerpt with a real count.
    assert "run_command" in assess_human
    assert "1139" in assess_human
    # And the prompt fragment contract (plan_assess_instructions) must be in the system prompt.
    system = msgs[0].content
    assert "**assessment_reasoning**" in system
    assert "Do NOT restate the user's request" in system


def test_replay_also_visible_to_plan_generate() -> None:
    """plan_generate sees the same anchor (no fragment change, just envelope thread)."""
    state = LoopState(goal="count files", thread_id="t1", iteration=1)
    ex = Executor(object(), max_parallel_steps=4)
    steps = [StepAction(id="s1", description="count py", expected_output="n")]
    ex._append_parallel_wave_ledger(
        state,
        steps,
        [_ok_step("s1", "Counted .py: 1139", "run_command", "1139")],
    )
    state.iteration = 2

    msgs = PromptBuilder().build_plan_messages(
        "count files", state, PlanContext(), plan_phase="generate"
    )
    gen_human = msgs[-1].content
    assert "<PRIOR_PROGRESS>" in gen_human
    assert "1139" in gen_human


def test_stale_digest_drops_out_of_prompt_after_two_iterations() -> None:
    """Digest from iter=1 is hidden when current_iteration = 3 (delta > 1)."""
    state = LoopState(goal="count files", thread_id="t1", iteration=1)
    ex = Executor(object(), max_parallel_steps=4)
    ex._append_parallel_wave_ledger(
        state,
        [StepAction(id="s1", description="count", expected_output="n")],
        [_ok_step("s1", "Counted .py: 1139", "run_command", "1139")],
    )
    state.iteration = 3

    msgs = PromptBuilder().build_plan_messages(
        "count files", state, PlanContext(), plan_phase="assess"
    )
    assert "<PRIOR_PROGRESS>" not in msgs[-1].content
