"""Unit tests for plan-phase ledger compaction (A2 + C1 + D1)."""

from __future__ import annotations

import soothe.foundation.loop.state.schemas  # noqa: F401 — break circular import
from soothe.foundation.loop.planning.ledger_compaction import (
    compact_plan_assess_ai_dump,
    compact_planning_human_content,
)
from soothe.foundation.loop.state.schemas import StatusAssessment

# --- New format tests ---


def test_compact_human_strips_timestamp_line() -> None:
    content = (
        "GOAL:\ndo the thing\n\n"
        "PRIOR PROGRESS:\nhint=low\n\n"
        "TIMESTAMP: 2026-06-02T10:19:55+00:00"
    )
    out = compact_planning_human_content(content)
    assert "TIMESTAMP:" not in out
    assert "2026-06-02" not in out
    assert "PRIOR PROGRESS:" in out, "non-volatile blocks must be preserved"


def test_compact_human_rewrites_goal_to_goal_recap() -> None:
    content = "GOAL:\nweight stuff\n\nINTENT: agentic (complexity: medium)"
    out = compact_planning_human_content(content)
    assert "GOAL:\n" not in out
    assert "GOAL RECAP:" in out
    assert "weight stuff" in out


def test_compact_human_new_format_is_idempotent() -> None:
    content = "GOAL:\nx\n\nTIMESTAMP: 2026-06-02T10:19:55+00:00"
    once = compact_planning_human_content(content)
    twice = compact_planning_human_content(once)
    assert once == twice


# --- Legacy XML format tests (dual-format support) ---


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


# --- Common ---


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
