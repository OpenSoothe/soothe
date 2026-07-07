"""Unit tests for plan-phase ledger compaction (D1 + execute human)."""

from __future__ import annotations

import soothe.foundation.sloop.state.schemas  # noqa: F401 — break circular import
from soothe.foundation.sloop.cognition.ledger_compaction import (
    compact_execute_human_content,
    compact_planning_human_content,
)
from soothe.foundation.sloop.state.schemas import StepAction


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


def test_compact_human_passthrough_when_no_markers() -> None:
    assert compact_planning_human_content("just some plain text") == "just some plain text"
    assert compact_planning_human_content("") == ""


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
