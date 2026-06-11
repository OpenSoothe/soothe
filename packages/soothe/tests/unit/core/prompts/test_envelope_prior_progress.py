"""Unit tests for <PRIOR_PROGRESS> rendering in plan-context envelope (RFC-227)."""

from __future__ import annotations

from soothe.foundation.loop.prompts.user_envelope import (
    PRIOR_PROGRESS_MAX_CHARS,
    build_plan_context_envelope,
)
from soothe.foundation.loop.state.schemas import PriorProgressDigest, ToolCallHead


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
        derived_progress_hint="high",
    )
    base.update(overrides)
    return PriorProgressDigest(**base)


def test_envelope_renders_prior_progress_block_when_fresh() -> None:
    out = build_plan_context_envelope(
        goal="count files",
        prior_progress=_digest(),
        current_iteration=2,
    )
    assert "<PRIOR_PROGRESS>" in out
    assert "iter=1 wave=0 done=2 failed=0 hint=high" in out
    # Tools section removed — only evidence remains
    assert "- run_command:" not in out
    assert '- "Counted .py: 1139"' in out


def test_envelope_omits_block_when_no_digest() -> None:
    out = build_plan_context_envelope(goal="g", current_iteration=0)
    assert "<PRIOR_PROGRESS>" not in out


def test_envelope_omits_stale_digest() -> None:
    # Digest from iteration=0; current iteration is 3 (delta > 1) → stale.
    out = build_plan_context_envelope(
        goal="g",
        prior_progress=_digest(iteration=0),
        current_iteration=3,
    )
    assert "<PRIOR_PROGRESS>" not in out


def test_envelope_keeps_digest_one_iteration_behind() -> None:
    # iteration=current-1 is the freshest possible state for the assess call.
    out = build_plan_context_envelope(
        goal="g",
        prior_progress=_digest(iteration=2),
        current_iteration=3,
    )
    assert "<PRIOR_PROGRESS>" in out


def test_envelope_omits_tools_section_entirely() -> None:
    # IG-XXX: Tools section removed to avoid empty argument strings confusing LLM
    out = build_plan_context_envelope(
        goal="g",
        prior_progress=_digest(
            tool_calls=[ToolCallHead(name="run_command", head="some args")],
            evidence_excerpts=["result text"],
            derived_progress_hint="medium",
        ),
        current_iteration=1,
    )
    # No tools section rendered, even with non-empty head
    assert "tools:" not in out
    assert "- run_command:" not in out
    # Evidence still rendered
    assert '- "result text"' in out


def test_envelope_hard_caps_at_600_chars_drops_evidence() -> None:
    huge_evidence = ["x" * 199 for _ in range(3)]
    out = build_plan_context_envelope(
        goal="g",
        prior_progress=_digest(
            tool_calls=[ToolCallHead(name="run_command", head=f"line {i}") for i in range(8)],
            evidence_excerpts=huge_evidence,
            derived_progress_hint="high",
        ),
        current_iteration=2,
    )
    start = out.find("<PRIOR_PROGRESS>")
    end = out.find("</PRIOR_PROGRESS>") + len("</PRIOR_PROGRESS>")
    block = out[start:end]
    assert len(block) <= PRIOR_PROGRESS_MAX_CHARS
    # Evidence dropped when budget exceeded; no tools section exists
    assert "tools:" not in block


def test_envelope_treats_no_current_iteration_as_fresh() -> None:
    out = build_plan_context_envelope(
        goal="g",
        prior_progress=_digest(iteration=0),
    )
    assert "<PRIOR_PROGRESS>" in out


def test_envelope_escapes_quotes_in_excerpts() -> None:
    out = build_plan_context_envelope(
        goal="g",
        prior_progress=_digest(
            tool_calls=[ToolCallHead(name="run_command", head='echo "hi"')],
            evidence_excerpts=['said: "found"'],
        ),
        current_iteration=2,
    )
    # Tools section removed, so no tool escaping check
    assert "tools:" not in out
    # Evidence excerpt still JSON-escaped
    assert '- "said: \\"found\\""' in out
