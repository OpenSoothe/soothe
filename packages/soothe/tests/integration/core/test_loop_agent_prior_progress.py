"""Integration: executor produces digest, plan-builder threads it to assess prompt.

Replays the "count file types" scenarios from the motivating traces
(``279a91c70f73f5b71fb31a5b61370f45``, ``87e146e39c2c675a527bb7164b47b04d``):
after a wave of tool calls, the next plan-assess prompt MUST carry concrete
evidence the LLM can cite (tool names from ``AIMessage.tool_calls`` and a
ledger-body excerpt).
"""

from __future__ import annotations

from unittest.mock import MagicMock

from langchain_core.messages import AIMessage, AIMessageChunk, ToolMessage

from soothe.foundation.loop.engine.executor import Executor
from soothe.foundation.loop.engine.step_wave_types import _ExecuteStepResult
from soothe.foundation.loop.prompts import PromptBuilder
from soothe.foundation.loop.state.schemas import (
    LoopState,
    StepAction,
    StepResult,
)
from soothe.protocols.planner import PlanContext


def _mock_context_engine() -> MagicMock:
    """Create a mock ContextEngine for Executor tests (RFC-624 Phase 4).

    The executor requires ContextEngine for ledger recording. Tests that don't
    need actual CE persistence can use this mock.
    """
    mock_ce = MagicMock()
    mock_ce.ledger.record_message = MagicMock()
    return mock_ce


def _payload(
    *,
    step_id: str,
    final_text: str,
    tool_calls: list[dict],
    tool_messages: list[ToolMessage] | None = None,
) -> _ExecuteStepResult:
    """Production-shaped gather_results entry.

    ``_stream_and_collect`` returns _ExecuteStepResult dataclass (IG-493);
    tests that need tool-result evidence in PriorProgressDigest may pass
    ToolMessages via ``tool_messages`` (test-only convenience).
    """
    messages: list = [
        AIMessage(content="", tool_calls=tool_calls),
    ]
    if tool_messages:
        messages.extend(tool_messages)
    messages.append(AIMessage(content=final_text))
    return _ExecuteStepResult(
        events=[],
        step_result=StepResult(
            step_id=step_id,
            success=True,
            outcome={"type": "code_exec"},
            duration_ms=12,
            thread_id="t1",
            tool_call_count=len(tool_calls),
        ),
        messages=messages,
        delegate_final="",
        output=final_text,
    )


def test_count_file_types_replay_assess_prompt_carries_evidence() -> None:
    """After 3 successful tool-call waves for file-count steps, the next
    plan-assess prompt must contain PRIOR PROGRESS: with tool names and an
    evidence excerpt — no goal restatement.
    """
    state = LoopState(
        goal="count all file types of the project",
        thread_id="t1",
        iteration=1,
    )
    ex = Executor(object(), max_parallel_steps=4, context_engine=_mock_context_engine())

    steps = [
        StepAction(id="s1", description="count .py files", expected_output="n"),
        StepAction(id="s2", description="count .json files", expected_output="n"),
        StepAction(id="s3", description="count .md files", expected_output="n"),
    ]
    wave_results = [
        _payload(
            step_id="s1",
            final_text="Counted .py: 1139",
            tool_calls=[
                {
                    "name": "run_command",
                    "args": {"command": "find . -name '*.py' | wc -l"},
                    "id": "a",
                }
            ],
        ),
        _payload(
            step_id="s2",
            final_text="Counted .json: 665",
            tool_calls=[
                {
                    "name": "run_command",
                    "args": {"command": "find . -name '*.json' | wc -l"},
                    "id": "b",
                }
            ],
        ),
        _payload(
            step_id="s3",
            final_text="Counted .md: 217",
            tool_calls=[
                {
                    "name": "run_command",
                    "args": {"command": "find . -name '*.md' | wc -l"},
                    "id": "c",
                }
            ],
        ),
    ]

    ex._append_parallel_wave_ledger(state, steps, wave_results)

    digest = state.prior_progress
    assert digest is not None
    assert digest.steps_completed == 3
    assert digest.steps_failed == 0
    assert digest.derived_progress_hint == "high"
    assert [t.name for t in digest.tool_calls] == [
        "run_command",
        "run_command",
        "run_command",
    ]
    assert digest.tool_calls[0].head.startswith("find . -name '*.py'")
    assert any("1139" in e for e in digest.evidence_excerpts)

    state.iteration = 2

    builder = PromptBuilder()
    msgs = builder.build_plan_messages(
        "count all file types of the project", state, PlanContext(), plan_phase="assess"
    )
    assess_human = msgs[-1].content
    assert "PRIOR PROGRESS:" in assess_human
    assert "1139" in assess_human  # Evidence excerpt from file count
    system = msgs[0].content
    assert "**assessment_reasoning**" in system
    assert "Do NOT restate the user's request" in system


def test_replay_also_visible_to_plan_generate() -> None:
    state = LoopState(goal="count files", thread_id="t1", iteration=1)
    ex = Executor(object(), max_parallel_steps=4, context_engine=_mock_context_engine())
    steps = [StepAction(id="s1", description="count py", expected_output="n")]
    ex._append_parallel_wave_ledger(
        state,
        steps,
        [
            _payload(
                step_id="s1",
                final_text="Counted .py: 1139",
                tool_calls=[{"name": "run_command", "args": {"command": "wc -l"}, "id": "a"}],
            )
        ],
    )
    state.iteration = 2

    msgs = PromptBuilder().build_plan_messages(
        "count files", state, PlanContext(), plan_phase="generate"
    )
    gen_human = msgs[-1].content
    assert "PRIOR PROGRESS:" in gen_human
    assert "1139" in gen_human


def test_stale_digest_drops_out_of_prompt_after_two_iterations() -> None:
    state = LoopState(goal="count files", thread_id="t1", iteration=1)
    ex = Executor(object(), max_parallel_steps=4, context_engine=_mock_context_engine())
    ex._append_parallel_wave_ledger(
        state,
        [StepAction(id="s1", description="count", expected_output="n")],
        [
            _payload(
                step_id="s1",
                final_text="Counted .py: 1139",
                tool_calls=[{"name": "run_command", "args": {"command": "wc -l"}, "id": "a"}],
            )
        ],
    )
    state.iteration = 3

    msgs = PromptBuilder().build_plan_messages(
        "count files", state, PlanContext(), plan_phase="assess"
    )
    assert "PRIOR PROGRESS:" not in msgs[-1].content


def test_production_shape_chunked_text_with_empty_final_aimessage() -> None:
    """Regression for trace 87e146e3: production AIMessage at end of stream has
    empty content; assistant text lives in earlier AIMessageChunk entries.
    Digest must still surface that text via the ledger-body extractor."""
    ex = Executor(object(), max_parallel_steps=4, context_engine=_mock_context_engine())
    state = LoopState(goal="count files", thread_id="t1", iteration=1)
    steps = [StepAction(id="s1", description="count", expected_output="n")]

    # No ToolMessage in messages list — matches what _stream_and_collect returns.
    payload = _ExecuteStepResult(
        events=[],
        step_result=StepResult(
            step_id="s1",
            success=True,
            outcome={"type": "code_exec"},
            duration_ms=5,
            thread_id="t1",
            tool_call_count=2,
        ),
        messages=[
            AIMessage(
                content="",
                tool_calls=[
                    {"name": "run_command", "args": {"command": "find . -type f"}, "id": "a"},
                    {"name": "read_file", "args": {"path": "pyproject.toml"}, "id": "b"},
                ],
            ),
            AIMessageChunk(content="The repo has "),
            AIMessageChunk(content="1139 Python files and 665 JSON files."),
            AIMessage(content=""),
        ],
        delegate_final="",
        output="The repo has 1139 Python files and 665 JSON files.",
    )
    ex._append_parallel_wave_ledger(state, steps, [payload])

    state.iteration = 2
    msgs = PromptBuilder().build_plan_messages(
        "count files", state, PlanContext(), plan_phase="assess"
    )
    assess_human = msgs[-1].content
    assert "PRIOR PROGRESS:" in assess_human
    # Evidence comes from chunked assistant text via _ledger_execute_ai_content.
    assert "1139 Python files" in assess_human
