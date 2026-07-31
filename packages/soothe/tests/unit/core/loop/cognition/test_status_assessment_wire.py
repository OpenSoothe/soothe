"""StatusAssessment wire salvage (loop fa03 assess envelope stall)."""

from __future__ import annotations

import pytest

from soothe.sloop.cognition.status_assessment_wire import (
    coerce_status_assessment_wire_dict,
    parse_status_assessment_payload,
)
from soothe.sloop.cognition.wire_envelope import unwrap_schema_envelope
from soothe.sloop.state.schemas import StatusAssessment


def test_unwraps_section_envelope() -> None:
    """The exact payload loop fa03 rejected must validate."""
    coerced = coerce_status_assessment_wire_dict(
        {
            "PLAN_ASSESS": {
                "status": "continue",
                "goal_progress": "low",
                "assessment_reasoning": "Repairs still pending.",
                "require_goal_completion": False,
                "terminal_readiness": "not_ready",
                "gap_alignment": True,
            }
        }
    )

    assert StatusAssessment(**coerced).status == "continue"
    assert coerced["goal_progress"] == "low"


def test_valid_payload_passes_through() -> None:
    payload = {"status": "done", "goal_progress": "complete"}
    assert coerce_status_assessment_wire_dict(payload) == payload


def test_envelope_without_marker_is_left_alone() -> None:
    """A single-key dict that is not an envelope must not be peeled."""
    payload = {"assessment_reasoning": "no status field here"}
    assert coerce_status_assessment_wire_dict(payload) == payload


def test_normalizes_enum_case_and_drops_unknown_values() -> None:
    coerced = coerce_status_assessment_wire_dict(
        {"status": "Continue", "goal_progress": "PARTIAL", "terminal_readiness": "ready"}
    )

    assert coerced["status"] == "continue"
    assert coerced["terminal_readiness"] == "ready"
    # "partial" is not a progress bucket — drop it so the schema default applies.
    assert "goal_progress" not in coerced
    assert StatusAssessment(**coerced).goal_progress == "none"


def test_parses_tag_wrapped_yaml() -> None:
    """The raw fallback shape loop fa03 failed to parse."""
    text = (
        "<PLAN_ASSESS>\n"
        'status: "continue"\n'
        'goal_progress: "low"\n'
        'assessment_reasoning: "Critical actions remain."\n'
        "</PLAN_ASSESS>"
    )

    parsed = parse_status_assessment_payload(text)
    assessment = StatusAssessment(**coerce_status_assessment_wire_dict(parsed))

    assert assessment.status == "continue"
    assert assessment.goal_progress == "low"


def test_parses_plain_json() -> None:
    parsed = parse_status_assessment_payload('{"status": "replan"}')
    assert parsed == {"status": "replan"}


def test_rejects_non_mapping_payload() -> None:
    with pytest.raises(ValueError, match="expected a mapping"):
        parse_status_assessment_payload("- just\n- a list")


def test_unwrap_stops_at_non_dict_inner() -> None:
    payload = {"PLAN_ASSESS": "continue"}
    assert unwrap_schema_envelope(payload, marker_key="status") == payload
