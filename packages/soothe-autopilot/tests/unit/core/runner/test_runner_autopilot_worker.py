"""Tests for the autopilot worker mixin (RFC-222 revised, Phase B).

Covers the worker-side contract:
- astream(autopilot_job=...) routes to _run_autopilot_job
- A single GoalCompletionChunk is emitted, with the right outcome
- The chunk type matches RFC-403 internal namespace
- Solo path (autopilot_job=None) is unaffected
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from soothe.goal_contracts import GoalDispatchContextBundle
from soothe.protocols.runner import GoalDispatchEnvelope
from soothe.sloop.state.schemas import PlanResult

from soothe_autopilot.runner import AutopilotSootheRunner

_COMPLETION_TYPE = "soothe.internal.autopilot.goal_completion"


# ---- Helpers / fakes ---------------------------------------------------


def _job(goal_id: str = "g1", attempt: int = 1) -> GoalDispatchEnvelope:
    return GoalDispatchEnvelope(
        goal_id=goal_id,
        goal_description="do thing",
        merged_context=GoalDispatchContextBundle(),
        deadline_seconds=None,
        attempt=attempt,
    )


def _plan_result(*, is_done: bool, status: str = "complete") -> PlanResult:
    """Create a minimal PlanResult; .is_done() returns ``is_done``."""
    pr = MagicMock(spec=PlanResult)
    pr.is_done = MagicMock(return_value=is_done)
    pr.status = status
    pr.evidence_summary = "summary text"
    pr.full_output = None
    pr.decision = None
    pr.effects = []
    return pr


class _BareMixin(AutopilotSootheRunner):
    """Concrete instantiation of the runner for direct method tests.

    The streaming method needs ``self._agent`` (backed by ``_core_agent``),
    ``self._planner``, ``self._config`` — provide MagicMocks so tests that
    don't call ``_run_autopilot_job`` work without a real SootheRunner.
    """

    def __init__(self) -> None:
        self._core_agent = MagicMock()
        self._planner = MagicMock()
        self._config = MagicMock()
        self._materialize_core_agent = AsyncMock(return_value=self._agent)
        self.get_sloop_shared_pool = AsyncMock(return_value=None)


# ---- Helper-method tests (no StrangeLoop involvement) -------------------


class TestDeriveOutcome:
    def test_none_plan_result_is_needs_replan(self) -> None:
        # / empty/clarification terminal → needs_replan (host send_back)
        assert AutopilotSootheRunner._derive_outcome(None) == "needs_replan"

    def test_status_continue_is_needs_replan(self) -> None:
        pr = _plan_result(is_done=False, status="continue")
        assert AutopilotSootheRunner._derive_outcome(pr) == "needs_replan"

    def test_is_done_true_is_completed(self) -> None:
        pr = _plan_result(is_done=True)
        assert AutopilotSootheRunner._derive_outcome(pr) == "completed"

    def test_status_replan_is_needs_replan(self) -> None:
        pr = _plan_result(is_done=False, status="replan")
        assert AutopilotSootheRunner._derive_outcome(pr) == "needs_replan"

    def test_status_in_progress_is_needs_replan(self) -> None:
        pr = _plan_result(is_done=False, status="in_progress")
        assert AutopilotSootheRunner._derive_outcome(pr) == "needs_replan"

    def test_other_status_is_failed(self) -> None:
        pr = _plan_result(is_done=False, status="abandoned")
        assert AutopilotSootheRunner._derive_outcome(pr) == "failed"


class TestBuildContribution:
    def test_none_plan_result_yields_empty_contribution(self) -> None:
        c = AutopilotSootheRunner._build_contribution(None)
        assert c.findings == []
        assert c.plan_steps_executed == []
        assert c.tool_call_stats.total_calls() == 0

    def test_plan_result_with_summary_creates_one_finding(self) -> None:
        pr = _plan_result(is_done=True)
        c = AutopilotSootheRunner._build_contribution(pr)
        assert len(c.findings) == 1
        assert "summary text" in c.findings[0].summary
        assert c.findings[0].relevance_score == 0.8

    def test_plan_result_with_no_summary_creates_no_findings(self) -> None:
        pr = _plan_result(is_done=True)
        pr.evidence_summary = ""
        pr.full_output = None
        c = AutopilotSootheRunner._build_contribution(pr)
        assert c.findings == []

    def test_full_output_synthesizes_finding_when_summary_empty(self) -> None:
        pr = _plan_result(is_done=True)
        pr.evidence_summary = ""
        pr.full_output = "hello\n"
        c = AutopilotSootheRunner._build_contribution(pr)
        assert len(c.findings) == 1
        assert "hello" in c.findings[0].summary

    def test_completion_chunk_uses_full_output_as_evidence(self) -> None:
        mixin = _BareMixin()
        pr = _plan_result(is_done=True)
        pr.evidence_summary = ""
        pr.full_output = "echo ok"
        chunk = mixin._goal_completion_chunk(_job(), outcome="completed", plan_result=pr)
        _, _, payload = chunk
        assert payload["evidence_summary"] == "echo ok"

    def test_decision_steps_become_plan_steps(self) -> None:
        pr = _plan_result(is_done=True)
        decision = MagicMock()
        decision.steps = [
            {"id": "A-01", "description": "step A"},
            {"id": "A-02", "description": "step B"},
        ]
        pr.decision = decision
        c = AutopilotSootheRunner._build_contribution(pr)
        assert len(c.plan_steps_executed) == 2
        assert c.plan_steps_executed[0].id == "A-01"
        assert c.plan_steps_executed[0].action == "step A"
        assert c.plan_steps_executed[1].action == "step B"

    def test_wave_plan_in_long_full_output_becomes_bare_json_finding(self) -> None:
        """WavePlan buried past the 2k prose truncate must still reach findings."""
        pr = _plan_result(is_done=True)
        pr.evidence_summary = ""
        padding = "x" * 2500
        wave = (
            '{"wave_slices":["frontend","api","tests"],'
            '"independence":"disjoint",'
            '"rationale":"layers"}'
        )
        pr.full_output = padding + "\n" + wave + "\n"
        c = AutopilotSootheRunner._build_contribution(pr)
        assert c.findings
        bare = c.findings[0].summary
        assert "wave_slices" in bare
        assert "frontend" in bare
        from soothe_autopilot.rails.wave_plan import parse_wave_plan_payload

        plan = parse_wave_plan_payload(bare)
        assert plan is not None
        assert plan.resolved_slice_ids() == ["frontend", "api", "tests"]
        # Prose finding may also exist (truncated); WavePlan finding is first.
        assert c.findings[0].relevance_score == 1.0

    def test_nested_wave_plan_wrapper_extracted_from_evidence(self) -> None:
        pr = _plan_result(is_done=True)
        pr.evidence_summary = (
            '{"job_id":"abc","wave_plan":{"wave_slices":["a","b"],'
            '"independence":"disjoint","rationale":"r"}}'
        )
        pr.full_output = None
        c = AutopilotSootheRunner._build_contribution(pr)
        assert c.findings
        from soothe_autopilot.rails.wave_plan import parse_wave_plan_payload

        plan = parse_wave_plan_payload(c.findings[0].summary)
        assert plan is not None
        assert plan.resolved_slice_ids() == ["a", "b"]


class TestGoalCompletionChunk:
    def test_chunk_format_is_custom_namespace(self) -> None:
        mixin = _BareMixin()
        job = _job("g1")
        chunk = mixin._goal_completion_chunk(
            job, outcome="completed", plan_result=_plan_result(is_done=True)
        )
        namespace, mode, payload = chunk
        assert namespace == ()
        assert mode == "custom"
        assert payload["type"] == _COMPLETION_TYPE
        assert payload["goal_id"] == "g1"
        assert payload["outcome"] == "completed"
        assert payload["attempt"] == 1
        assert "context_contribution" in payload

    def test_failed_outcome_with_error_text_includes_error(self) -> None:
        mixin = _BareMixin()
        chunk = mixin._goal_completion_chunk(
            _job(), outcome="failed", plan_result=None, error_text="boom"
        )
        _, _, payload = chunk
        assert payload["outcome"] == "failed"
        assert payload["error_text"] == "boom"
        # Empty contribution is still present (worker contract).
        assert payload["context_contribution"]["findings"] == []

    def test_contribution_is_json_serializable(self) -> None:
        """The contribution must be a plain dict (not a Pydantic instance)
        so the existing IPC pickling path doesn't trip on it."""
        mixin = _BareMixin()
        chunk = mixin._goal_completion_chunk(
            _job(), outcome="completed", plan_result=_plan_result(is_done=True)
        )
        _, _, payload = chunk
        assert isinstance(payload["context_contribution"], dict)


# ---- Streaming-path tests (StrangeLoop stubbed) -------------------------


class _FakeStrangeLoop:
    """Stub StrangeLoop yielding canned (event_type, event_data) tuples."""

    def __init__(self, *_args: Any, **_kwargs: Any) -> None:
        pass

    def make_progress(self, events: list[tuple[str, Any]]):
        self._events = events
        return self

    async def run_with_progress(self, **kwargs: Any):  # noqa: ANN401
        for evt in self._events:
            yield evt


def _patch_strange_loop(monkeypatch: pytest.MonkeyPatch, fake: _FakeStrangeLoop) -> None:
    """Replace StrangeLoop where the mixin imports it (lazy import path)."""

    def _factory(*_args: Any, **_kwargs: Any) -> _FakeStrangeLoop:
        return fake

    monkeypatch.setattr(
        "soothe.sloop.strange_loop.StrangeLoop",
        _factory,
    )


@pytest.mark.asyncio
async def test_stream_initializes_checkpointer_before_strange_loop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pr = _plan_result(is_done=True)
    fake = _FakeStrangeLoop().make_progress([("completed", {"result": pr})])
    _patch_strange_loop(monkeypatch, fake)

    mixin = _BareMixin()
    _ = [
        c
        async for c in mixin._run_autopilot_job(
            _job(), thread_id="t1", workspace="/tmp", max_iterations=8
        )
    ]

    mixin._materialize_core_agent.assert_awaited_once()


@pytest.mark.asyncio
async def test_stream_emits_completion_chunk_at_end(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Happy path: PlanResult.is_done() True → outcome 'completed'."""
    pr = _plan_result(is_done=True)
    fake = _FakeStrangeLoop().make_progress(
        [
            ("plan", {"action": "first plan"}),
            ("iteration_started", {"iter": 1}),
            ("completed", {"result": pr}),
        ]
    )
    _patch_strange_loop(monkeypatch, fake)

    mixin = _BareMixin()
    chunks = [
        c
        async for c in mixin._run_autopilot_job(
            _job(),
            thread_id="t1",
            workspace="/tmp/ws",
            max_iterations=8,
        )
    ]

    # First chunk is goal_started; last is goal_completion.
    first_payload = chunks[0][2]
    last_payload = chunks[-1][2]
    assert first_payload["type"] == "soothe.internal.autopilot.goal_started"
    assert last_payload["type"] == _COMPLETION_TYPE
    assert last_payload["outcome"] == "completed"

    # Intermediate progress events forwarded as namespaced custom chunks.
    intermediate_types = [c[2]["type"] for c in chunks[1:-1]]
    assert "soothe.internal.autopilot.progress.plan" in intermediate_types
    assert "soothe.internal.autopilot.progress.iteration_started" in intermediate_types


@pytest.mark.asyncio
async def test_stream_failed_plan_result_yields_failed_outcome(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pr = _plan_result(is_done=False, status="abandoned")
    fake = _FakeStrangeLoop().make_progress([("completed", {"result": pr})])
    _patch_strange_loop(monkeypatch, fake)

    mixin = _BareMixin()
    chunks = [
        c
        async for c in mixin._run_autopilot_job(
            _job(), thread_id="t1", workspace="/tmp", max_iterations=8
        )
    ]
    last_payload = chunks[-1][2]
    assert last_payload["type"] == _COMPLETION_TYPE
    assert last_payload["outcome"] == "failed"


@pytest.mark.asyncio
async def test_stream_needs_replan_when_status_is_replan(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pr = _plan_result(is_done=False, status="replan")
    fake = _FakeStrangeLoop().make_progress([("completed", {"result": pr})])
    _patch_strange_loop(monkeypatch, fake)

    mixin = _BareMixin()
    chunks = [
        c
        async for c in mixin._run_autopilot_job(
            _job(), thread_id="t1", workspace="/tmp", max_iterations=8
        )
    ]
    assert chunks[-1][2]["outcome"] == "needs_replan"


@pytest.mark.asyncio
async def test_stream_handles_sloop_exception(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If StrangeLoop raises mid-stream, emit a failed GoalCompletionChunk."""

    class _BoomError(RuntimeError):
        pass

    class _RaisingFakeStrangeLoop(_FakeStrangeLoop):
        async def run_with_progress(self, **kwargs: Any):
            yield ("plan", {"action": "first"})
            raise _BoomError("kaboom")

    fake = _RaisingFakeStrangeLoop()
    _patch_strange_loop(monkeypatch, fake)

    mixin = _BareMixin()
    chunks = [
        c
        async for c in mixin._run_autopilot_job(
            _job(),
            thread_id="t1",
            workspace="/tmp",
            max_iterations=8,
        )
    ]
    last_payload = chunks[-1][2]
    assert last_payload["type"] == _COMPLETION_TYPE
    assert last_payload["outcome"] == "failed"
    assert "kaboom" in last_payload["error_text"]


@pytest.mark.asyncio
async def test_stream_uses_provided_thread_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    class _CapturingFake(_FakeStrangeLoop):
        async def run_with_progress(self, **kwargs: Any):
            captured.update(kwargs)
            yield ("completed", {"result": _plan_result(is_done=True)})

    _patch_strange_loop(monkeypatch, _CapturingFake())
    mixin = _BareMixin()
    _ = [
        c
        async for c in mixin._run_autopilot_job(
            _job(), thread_id="custom-tid", workspace="/tmp", max_iterations=8
        )
    ]
    assert captured["thread_id"] == "custom-tid"
    assert captured["loop_id"] == "custom-tid"
    assert captured["workspace"] == "/tmp"


@pytest.mark.asyncio
async def test_stream_synthesizes_thread_id_when_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    class _CapturingFake(_FakeStrangeLoop):
        async def run_with_progress(self, **kwargs: Any):
            captured.update(kwargs)
            yield ("completed", {"result": _plan_result(is_done=True)})

    _patch_strange_loop(monkeypatch, _CapturingFake())
    mixin = _BareMixin()
    _ = [
        c
        async for c in mixin._run_autopilot_job(
            _job("g42", attempt=3),
            thread_id=None,
            workspace="/tmp",
            max_iterations=8,
        )
    ]
    # Synthesized form per the spec.
    assert captured["thread_id"] == "autopilot__goal_g42__attempt_3"


# ---- RFC-622: autopilot always forces auto-mode clarification policy --


@pytest.mark.asyncio
async def test_stream_forces_auto_clarification_policy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Autopilot is headless — the policy must be built with ``mode='auto'``
    and forwarded to ``StrangeLoop.run_with_progress``."""
    captured: dict[str, Any] = {}

    class _CapturingFake(_FakeStrangeLoop):
        async def run_with_progress(self, **kwargs: Any):
            captured.update(kwargs)
            yield ("completed", {"result": _plan_result(is_done=True)})

    _patch_strange_loop(monkeypatch, _CapturingFake())

    builder_calls: list[dict[str, Any]] = []
    sentinel_policy = object()

    def _stub_builder(
        _config: Any,
        *,
        mode: str,
        human_attached: bool = False,
        thread_id: str | None = None,
        loop_id: str | None = None,
    ) -> Any:
        builder_calls.append(
            {
                "mode": mode,
                "human_attached": human_attached,
                "thread_id": thread_id,
                "loop_id": loop_id,
            }
        )
        return sentinel_policy

    monkeypatch.setattr(
        "soothe.sloop.clarification.build_clarification_policy_for_runner",
        _stub_builder,
        raising=True,
    )

    mixin = _BareMixin()
    _ = [
        c
        async for c in mixin._run_autopilot_job(
            _job(), thread_id="t1", workspace="/tmp", max_iterations=8
        )
    ]

    # RFC-623: autopilot is headless — never wires the interactive fallback.
    # Langfuse correlation: the runner forwards thread_id/loop_id (both = tid).
    assert builder_calls == [
        {"mode": "auto", "human_attached": False, "thread_id": "t1", "loop_id": "t1"}
    ]
    assert captured["clarification_policy"] is sentinel_policy


@pytest.mark.asyncio
async def test_stream_continues_when_clarification_builder_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If the policy factory raises, the worker passes ``None`` and continues
    rather than failing the whole goal."""
    captured: dict[str, Any] = {}

    class _CapturingFake(_FakeStrangeLoop):
        async def run_with_progress(self, **kwargs: Any):
            captured.update(kwargs)
            yield ("completed", {"result": _plan_result(is_done=True)})

    _patch_strange_loop(monkeypatch, _CapturingFake())

    def _raising_builder(*_args: Any, **_kwargs: Any) -> Any:
        raise RuntimeError("no model")

    monkeypatch.setattr(
        "soothe.sloop.clarification.build_clarification_policy_for_runner",
        _raising_builder,
        raising=True,
    )

    mixin = _BareMixin()
    chunks = [
        c
        async for c in mixin._run_autopilot_job(
            _job(), thread_id="t1", workspace="/tmp", max_iterations=8
        )
    ]
    assert captured["clarification_policy"] is None
    assert chunks[-1][2]["outcome"] == "completed"


# ---- Preamble extraction helpers (RFC-222 §Goal-Report-Pair) -------------


class TestGoalDirectiveText:
    def test_no_guidance_returns_base(self) -> None:
        from soothe_autopilot.runner import _goal_directive_text

        job = _job()
        assert _goal_directive_text(job) == "do thing"

    def test_guidance_appended_as_section(self) -> None:
        from soothe_autopilot.runner import _goal_directive_text

        job = GoalDispatchEnvelope(
            goal_id="g1",
            goal_description="do thing",
            merged_context=GoalDispatchContextBundle(
                operator_guidance=["be careful", "commit often"]
            ),
        )
        text = _goal_directive_text(job)
        assert "do thing" in text
        assert "## Operator guidance" in text
        assert "- be careful" in text
        assert "- commit often" in text


class TestExtractPreamblePairs:
    def test_empty_bundle_returns_empty(self) -> None:
        from soothe_autopilot.runner import _extract_preamble_pairs

        assert _extract_preamble_pairs(_job()) == []

    def test_pairs_become_ledger_messages(self) -> None:
        from soothe.goal_contracts import (
            GoalDispatchContextBundle,
            GoalEffect,
            GoalReportAITurn,
            GoalReportUserTurn,
        )
        from soothe.sloop.utils.messages import LoopAIMessage, LoopHumanMessage

        from soothe_autopilot.runner import _extract_preamble_pairs

        u = GoalReportUserTurn(goal_id_origin="A", content="do root")
        a = GoalReportAITurn(
            goal_id_origin="A",
            outcome="completed",
            summary="root done",
            findings=["rf"],
            effects=[GoalEffect(kind="produce", ref="file.py", statement="created file")],
        )
        job = GoalDispatchEnvelope(
            goal_id="g1",
            goal_description="do X",
            merged_context=GoalDispatchContextBundle(preamble_messages=[u, a]),
        )
        pairs = _extract_preamble_pairs(job)
        assert len(pairs) == 2
        assert isinstance(pairs[0], LoopHumanMessage)
        assert pairs[0].phase == "preamble"
        assert pairs[0].content == "do root"
        assert isinstance(pairs[1], LoopAIMessage)
        assert pairs[1].phase == "preamble"
        assert "root done" in pairs[1].content


class TestRenderAITurnText:
    def test_full_render(self) -> None:
        from soothe.goal_contracts import GoalEffect, GoalReportAITurn

        from soothe_autopilot.runner import _render_ai_turn_text

        turn = GoalReportAITurn(
            goal_id_origin="A",
            outcome="completed",
            summary="root done",
            findings=["found X"],
            effects=[GoalEffect(kind="produce", ref="f.py", statement="made f")],
        )
        text = _render_ai_turn_text(turn)
        assert "root done" in text
        assert "- found X" in text
        assert "[produce] f.py: made f" in text

    def test_empty_turn_has_fallback(self) -> None:
        from soothe.goal_contracts import GoalReportAITurn

        from soothe_autopilot.runner import _render_ai_turn_text

        turn = GoalReportAITurn(goal_id_origin="A", outcome="failed", summary="")
        text = _render_ai_turn_text(turn)
        assert "outcome=failed" in text
