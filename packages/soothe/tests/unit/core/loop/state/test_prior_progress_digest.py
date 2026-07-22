"""Unit tests for RFC-227 PriorProgressDigest and ToolCallHead schemas."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from soothe.sloop.state.schemas import (
    LoopState,
    PriorProgressDigest,
    ToolCallHead,
)


class TestToolCallHead:
    def test_creation_with_head(self):
        t = ToolCallHead(name="run_command", head="1139")
        assert t.name == "run_command"
        assert t.head == "1139"

    def test_empty_head_allowed(self):
        t = ToolCallHead(name="read_file")
        assert t.head == ""

    def test_name_capped_at_64(self):
        with pytest.raises(ValidationError):
            ToolCallHead(name="x" * 65)

    def test_head_capped_at_120(self):
        with pytest.raises(ValidationError):
            ToolCallHead(name="run_command", head="y" * 121)


class TestPriorProgressDigest:
    def test_minimal_creation(self):
        d = PriorProgressDigest(iteration=0)
        assert d.iteration == 0
        assert d.wave_index == 0
        assert d.steps_completed == 0
        assert d.steps_failed == 0
        assert d.tool_calls == []
        assert d.evidence_excerpts == []
        assert d.step_summaries == []
        assert d.derived_progress_hint == "low"

    def test_full_round_trip(self):
        d = PriorProgressDigest(
            iteration=2,
            wave_index=1,
            steps_completed=3,
            steps_failed=0,
            tool_calls=[
                ToolCallHead(name="run_command", head="1139"),
                ToolCallHead(name="run_command", head="665"),
            ],
            evidence_excerpts=["Counted .py: 1139", "Counted .json: 665"],
            derived_progress_hint="high",
        )
        raw = d.model_dump_json()
        restored = PriorProgressDigest.model_validate_json(raw)
        assert restored == d
        assert restored.tool_calls[0].name == "run_command"

    def test_tool_calls_capped_at_8(self):
        with pytest.raises(ValidationError):
            PriorProgressDigest(
                iteration=0,
                tool_calls=[ToolCallHead(name="t") for _ in range(9)],
            )

    def test_evidence_excerpts_capped_at_3(self):
        with pytest.raises(ValidationError):
            PriorProgressDigest(
                iteration=0,
                evidence_excerpts=["a", "b", "c", "d"],
            )

    def test_hint_enum_validation(self):
        with pytest.raises(ValidationError):
            PriorProgressDigest(iteration=0, derived_progress_hint="complete")


class TestLoopStatePriorProgress:
    def test_default_is_none(self):
        s = LoopState(goal="g", thread_id="t")
        assert s.prior_progress is None

    def test_round_trips_through_json(self):
        digest = PriorProgressDigest(
            iteration=1,
            wave_index=0,
            steps_completed=2,
            tool_calls=[ToolCallHead(name="run_command", head="1139")],
            evidence_excerpts=["Counted .py: 1139"],
            derived_progress_hint="high",
        )
        s = LoopState(goal="g", thread_id="t", prior_progress=digest)
        raw = s.model_dump_json()
        restored = LoopState.model_validate_json(raw)
        assert restored.prior_progress is not None
        assert restored.prior_progress.iteration == 1
        assert restored.prior_progress.tool_calls[0].head == "1139"
        assert restored.prior_progress.derived_progress_hint == "high"

    def test_legacy_loop_state_without_field(self):
        # Older persisted checkpoints lack the field. Default must apply.
        legacy_json = '{"goal":"g","thread_id":"t"}'
        s = LoopState.model_validate_json(legacy_json)
        assert s.prior_progress is None
