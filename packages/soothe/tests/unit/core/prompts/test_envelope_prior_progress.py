"""Unit tests for PRIOR PROGRESS rendering in plan-context messages (RFC-227)."""

from __future__ import annotations

from soothe.prompts.user_message import (
    PRIOR_PROGRESS_MAX_CHARS,
    UserMessageBuilder,
)
from soothe.sloop.state.schemas import (
    PriorProgressDigest,
    ToolCallHead,
    WaveStepProgress,
)


def _digest(**overrides) -> PriorProgressDigest:
    base = dict(
        iteration=1,
        wave_index=0,
        steps_completed=2,
        steps_failed=0,
        tool_calls=[
            ToolCallHead(name="run_command", head="1139"),
            ToolCallHead(name="run_command", head="665"),
        ],
        evidence_excerpts=["Counted .py: 1139", "Counted .json: 665"],
        step_summaries=[
            WaveStepProgress(
                step_id="s1",
                description="count .py files",
                status="completed",
                outcome_preview="Counted .py: 1139",
            ),
            WaveStepProgress(
                step_id="s2",
                description="count .json files",
                status="completed",
                outcome_preview="Counted .json: 665",
            ),
        ],
        derived_progress_hint="high",
    )
    base.update(overrides)
    return PriorProgressDigest(**base)


def test_message_renders_prior_progress_when_fresh() -> None:
    builder = UserMessageBuilder()
    out = builder.build_plan_assess_message(
        goal="count files",
        prior_progress=_digest(),
        current_iteration=2,
    )
    assert "PRIOR PROGRESS:" in out
    assert "iter=1 wave=0 completed=2 failed=0" in out
    assert "progress_hint=high" not in out
    assert "- run_command:" not in out
    assert "- STEP [s1] count .py files (completed)" in out
    assert "  - outcome: Counted .py: 1139" in out


def test_message_omits_prior_progress_when_no_digest() -> None:
    builder = UserMessageBuilder()
    out = builder.build_plan_assess_message(goal="g", current_iteration=0)
    assert "PRIOR PROGRESS:" not in out


def test_message_omits_stale_digest() -> None:
    builder = UserMessageBuilder()
    out = builder.build_plan_assess_message(
        goal="g",
        prior_progress=_digest(iteration=0),
        current_iteration=3,
    )
    assert "PRIOR PROGRESS:" not in out


def test_message_keeps_digest_one_iteration_behind() -> None:
    builder = UserMessageBuilder()
    out = builder.build_plan_assess_message(
        goal="g",
        prior_progress=_digest(iteration=2),
        current_iteration=3,
    )
    assert "PRIOR PROGRESS:" in out


def test_message_omits_tools_section_entirely() -> None:
    builder = UserMessageBuilder()
    out = builder.build_plan_assess_message(
        goal="g",
        prior_progress=_digest(
            tool_calls=[ToolCallHead(name="run_command", head="some args")],
            evidence_excerpts=["result text"],
            step_summaries=[
                WaveStepProgress(
                    step_id="s1",
                    description="run check",
                    status="completed",
                    outcome_preview="result text",
                )
            ],
            derived_progress_hint="medium",
        ),
        current_iteration=1,
    )
    assert "tools:" not in out
    assert "- run_command:" not in out
    assert "  - outcome: result text" in out


def test_message_hard_caps_at_600_chars_drops_steps() -> None:
    huge_steps = [
        WaveStepProgress(
            step_id=f"s{i}",
            description=f"long step {i}",
            status="completed",
            outcome_preview="x" * 199,
        )
        for i in range(4)
    ]
    builder = UserMessageBuilder()
    out = builder.build_plan_assess_message(
        goal="g",
        prior_progress=_digest(
            step_summaries=huge_steps,
            tool_calls=[ToolCallHead(name="run_command", head=f"line {i}") for i in range(8)],
            evidence_excerpts=[step.outcome_preview for step in huge_steps[:3]],
            derived_progress_hint="high",
        ),
        current_iteration=2,
    )
    start = out.find("PRIOR PROGRESS:")
    # Extract the PRIOR PROGRESS section
    # Find the next section boundary (double newline after section content)
    section_text = out[start:]
    # Take up to the next section marker
    next_section = section_text.find("\n\n", len("PRIOR PROGRESS:\n"))
    if next_section != -1:
        block = section_text[:next_section]
    else:
        block = section_text
    assert len(block) <= PRIOR_PROGRESS_MAX_CHARS + len("PRIOR PROGRESS:\n")
    assert "tools:" not in block


def test_message_treats_no_current_iteration_as_fresh() -> None:
    builder = UserMessageBuilder()
    out = builder.build_plan_assess_message(
        goal="g",
        prior_progress=_digest(iteration=0),
    )
    assert "PRIOR PROGRESS:" in out


def test_message_renders_legacy_excerpt_fallback_without_step_summaries() -> None:
    builder = UserMessageBuilder()
    out = builder.build_plan_assess_message(
        goal="g",
        prior_progress=PriorProgressDigest(
            iteration=1,
            wave_index=0,
            steps_completed=1,
            evidence_excerpts=["Counted .py: 1139"],
            derived_progress_hint="medium",
        ),
        current_iteration=2,
    )
    assert "- STEP prior wave (completed)" in out
    assert "  - outcome: Counted .py: 1139" in out


def test_message_preserves_quotes_in_outcome_preview() -> None:
    builder = UserMessageBuilder()
    out = builder.build_plan_assess_message(
        goal="g",
        prior_progress=_digest(
            tool_calls=[ToolCallHead(name="run_command", head='echo "hi"')],
            step_summaries=[
                WaveStepProgress(
                    step_id="s1",
                    description="echo test",
                    status="completed",
                    outcome_preview='said: "found"',
                )
            ],
            evidence_excerpts=['said: "found"'],
        ),
        current_iteration=2,
    )
    assert "tools:" not in out
    assert '  - outcome: said: "found"' in out
