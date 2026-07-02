"""Unit tests for plan-phase ledger compaction (A2 + D1)."""

from __future__ import annotations

import soothe.foundation.sloop.state.schemas  # noqa: F401 — break circular import
from soothe.foundation.sloop.cognition.ledger_compaction import (
    compact_execute_human_content,
    compact_plan_assess_ai_dump,
    compact_planning_human_content,
)
from soothe.foundation.sloop.state.schemas import StatusAssessment, StepAction


def test_compact_human_rewrites_goal_to_goal_recap() -> None:
    content = "GOAL:\nweight stuff\n\nINTENT: agentic (complexity: medium)"
    out = compact_planning_human_content(content)
    assert "GOAL:\n" not in out
    assert "GOAL RECAP:" in out
    assert "weight stuff" in out


def test_compact_human_new_format_is_idempotent() -> None:
    content = "GOAL:\nx\n\nINTENT: agentic"
    once = compact_planning_human_content(content)
    twice = compact_planning_human_content(once)
    assert once == twice


def test_compact_human_strips_legacy_context_info_block() -> None:
    content = (
        "<USER_QUERY>\ndo the thing\n</USER_QUERY>\n"
        "<PRIOR_PROGRESS>\nhint=low\n</PRIOR_PROGRESS>\n"
        "<CONTEXT_INFO>\n<timestamp>2026-06-02T10:19:55Z</timestamp>\n<date>2026-06-02</date>\n</CONTEXT_INFO>"
    )
    out = compact_planning_human_content(content)
    assert "<CONTEXT_INFO>" not in out
    assert "<timestamp>" not in out
    assert "<PRIOR_PROGRESS>" in out, "non-volatile blocks must be preserved"


def test_compact_human_rewrites_legacy_user_query_to_goal_recap() -> None:
    content = "<USER_QUERY>\nweight stuff\n</USER_QUERY>\nmore"
    out = compact_planning_human_content(content)
    assert "<USER_QUERY>" not in out
    assert "</USER_QUERY>" not in out
    assert "<GOAL_RECAP>" in out
    assert "</GOAL_RECAP>" in out
    assert "weight stuff" in out


def test_compact_human_legacy_format_is_idempotent() -> None:
    content = "<USER_QUERY>\nx\n</USER_QUERY>\n<CONTEXT_INFO>\n<date>2026</date>\n</CONTEXT_INFO>"
    once = compact_planning_human_content(content)
    twice = compact_planning_human_content(once)
    assert once == twice


def test_compact_human_passthrough_when_no_markers() -> None:
    assert compact_planning_human_content("just some plain text") == "just some plain text"
    assert compact_planning_human_content("") == ""


def test_compact_plan_assess_drops_assessment_reasoning() -> None:
    """A2: prior `assessment_reasoning` text must not appear in the recorded dump."""
    response = StatusAssessment(
        status="replan",
        goal_progress="low",
        assessment_reasoning="Initial assessment: need to enumerate packages first.",
        require_goal_completion=False,
    )
    content = compact_plan_assess_ai_dump(response)
    assert "assessment_reasoning" not in content
    assert "Initial assessment" not in content
    assert "'status':" in content and "'replan'" in content
    assert "'goal_progress':" in content and "'low'" in content
    assert "require_goal_completion" in content


def test_compact_plan_assess_passthrough_for_none() -> None:
    assert compact_plan_assess_ai_dump(None) == ""


def test_compact_plan_assess_passthrough_for_non_pydantic() -> None:
    assert compact_plan_assess_ai_dump("raw string") == "raw string"


def test_compact_plan_assess_falls_back_when_no_recognized_fields() -> None:
    """Schema drift safety: unknown payload still gets stored, not dropped."""

    class _Foreign:
        def model_dump(self) -> dict:  # noqa: D401 — test stub
            return {"unrelated": 1, "other": "x"}

    out = compact_plan_assess_ai_dump(_Foreign())
    assert "unrelated" in out and "other" in out


def test_compact_plan_assess_survives_model_dump_failure() -> None:
    class _Broken:
        def model_dump(self) -> dict:
            raise RuntimeError("boom")

        def __str__(self) -> str:
            return "broken-repr"

    assert compact_plan_assess_ai_dump(_Broken()) == "broken-repr"


def test_compact_execute_human_content_uses_brief_and_expected_output() -> None:
    step = StepAction(
        id="01",
        description="Discover RFCs",
        full_description="Search docs/specs for autopilot RFC files and list scope areas.",
        expected_output="RFC list with scope summaries",
    )
    out = compact_execute_human_content(step)
    assert out.startswith("EXECUTION TASK:\n")
    assert "autopilot RFC" in out
    assert "EXPECTED OUTPUT:\nRFC list with scope summaries" in out


def test_compact_execute_human_content_omits_prior_evidence_from_envelope() -> None:
    step = StepAction(id="02", description="Fix failures", expected_output="tests pass")
    envelope = (
        "EXECUTION TASK:\nFix failures\n\n"
        "PRIOR STEP EVIDENCE:\nStep 01 — run tests (completed)\n---\nF821 in foo.py\n\n"
        "EXPECTED OUTPUT:\n- tests pass\n\n"
        "INSTRUCTIONS:\n- run tests"
    )
    out = compact_execute_human_content(step, envelope=envelope)
    assert "PRIOR STEP EVIDENCE:" not in out
    assert "F821 in foo.py" not in out
    assert "Fix failures" in out
