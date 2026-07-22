"""Tests for GoalDispatchEnvelope + LoopRunRequest.autopilot_job (RFC-222 revised)."""

from __future__ import annotations

import pickle

import pytest

from soothe.autopilot.engine_models import (
    GoalDispatchContextBundle,
    ParentFinding,
)
from soothe.protocols.runner import GoalDispatchEnvelope, LoopRunRequest


def _sample_bundle() -> GoalDispatchContextBundle:
    return GoalDispatchContextBundle(
        findings=[ParentFinding(goal_id_origin="g0", summary="prior finding")],
        cached_system_prompt_hash="prefix-h",
    )


class TestGoalDispatchEnvelope:
    def test_construct_minimal(self) -> None:
        job = GoalDispatchEnvelope(
            goal_id="g1",
            goal_description="do thing",
            merged_context=GoalDispatchContextBundle(),
        )
        assert job.goal_id == "g1"
        assert job.attempt == 1
        assert job.deadline_seconds is None

    def test_construct_with_deadline_and_retry(self) -> None:
        job = GoalDispatchEnvelope(
            goal_id="g1",
            goal_description="do thing",
            merged_context=GoalDispatchContextBundle(),
            deadline_seconds=600.0,
            attempt=3,
        )
        assert job.deadline_seconds == 600.0
        assert job.attempt == 3

    def test_is_frozen(self) -> None:
        job = GoalDispatchEnvelope(
            goal_id="g1",
            goal_description="do thing",
            merged_context=GoalDispatchContextBundle(),
        )
        with pytest.raises(Exception):  # FrozenInstanceError
            job.attempt = 5  # type: ignore[misc]

    def test_backward_compat_alias(self) -> None:
        """GoalDispatchEnvelope is the canonical dispatch envelope type."""
        job = GoalDispatchEnvelope(
            goal_id="g1",
            goal_description="do thing",
            merged_context=GoalDispatchContextBundle(),
        )
        assert job.goal_id == "g1"


class TestLoopRunRequestAutopilotJob:
    def test_default_is_none(self) -> None:
        """Existing callers that don't pass autopilot_job must be unaffected."""
        request = LoopRunRequest(
            loop_id="L1",
            thread_id="T1",
            user_input="hello",
        )
        assert request.autopilot_job is None

    def test_round_trip_pickle_when_none(self) -> None:
        """Existing IPC path (subprocess workers) pickles LoopRunRequest;
        the new optional field must not break that."""
        original = LoopRunRequest(
            loop_id="L1",
            thread_id="T1",
            user_input="hello",
        )
        decoded = pickle.loads(pickle.dumps(original))
        assert decoded.autopilot_job is None
        assert decoded.user_input == "hello"

    def test_round_trip_pickle_with_autopilot_job(self) -> None:
        """When set, the GoalDispatchEnvelope (incl. nested bundle) survives pickling."""
        bundle = _sample_bundle()
        request = LoopRunRequest(
            loop_id="L1",
            thread_id="T1",
            user_input="",
            autopilot_job=GoalDispatchEnvelope(
                goal_id="g1",
                goal_description="do thing",
                merged_context=bundle,
                deadline_seconds=120.0,
                attempt=2,
            ),
        )
        decoded = pickle.loads(pickle.dumps(request))
        assert decoded.autopilot_job is not None
        assert decoded.autopilot_job.goal_id == "g1"
        assert decoded.autopilot_job.attempt == 2
        assert decoded.autopilot_job.merged_context.cached_system_prompt_hash == "prefix-h"
        assert len(decoded.autopilot_job.merged_context.findings) == 1

    def test_attached_job_does_not_shadow_other_fields(self) -> None:
        bundle = _sample_bundle()
        request = LoopRunRequest(
            loop_id="L1",
            thread_id="T1",
            user_input="x",
            timeout_seconds=30.0,
            autonomous=True,
            max_iterations=5,
            autopilot_job=GoalDispatchEnvelope(
                goal_id="g1",
                goal_description="d",
                merged_context=bundle,
            ),
        )
        assert request.timeout_seconds == 30.0
        assert request.autonomous is True
        assert request.max_iterations == 5
        assert request.autopilot_job is not None
