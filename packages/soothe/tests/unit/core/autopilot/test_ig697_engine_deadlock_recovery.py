"""IG-697: engine-owned failed-goal / deadlock recovery."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from soothe.autopilot.engine_models import BackoffDecision
from soothe.autopilot.goal_dag_verifier import GoalDAGVerifier
from soothe.autopilot.monitor import AutopilotMonitor
from soothe.autopilot.monitor_models import DagHealthReport
from soothe.context import ContextEngine
from soothe.events.internal_bus import InternalEventBus


@pytest.fixture
def mock_config() -> MagicMock:
    cfg = MagicMock()
    cfg.agent = MagicMock()
    cfg.agent.autopilot = MagicMock()
    cfg.agent.autopilot.max_engine_recoveries = 2
    cfg.agent.autopilot.monitor_model_role = "think"
    cfg.create_chat_model = MagicMock(return_value=MagicMock())
    return cfg


def _monitor(ce: ContextEngine, config: MagicMock) -> AutopilotMonitor:
    return AutopilotMonitor(ce=ce, bus=InternalEventBus(), config=config)


@pytest.mark.asyncio
async def test_backoff_retries_failed_without_suspend(mock_config: MagicMock) -> None:
    ce = ContextEngine()
    goal = await ce.create_goal("flaky integrate", max_retries=2)
    await ce.fail_goal(goal.id, error="thin evidence")

    monitor = _monitor(ce, mock_config)
    decision = BackoffDecision(
        backoff_to_goal_id=goal.id,
        reason="retry same goal",
        new_directives=[],
        evidence_summary="insufficient merge evidence",
    )
    await monitor._apply_backoff_decision(decision, failed_goal_id=goal.id)

    after = await ce.get_goal(goal.id)
    assert after is not None
    assert after.status == "pending"
    assert after.retry_count == 1


@pytest.mark.asyncio
async def test_backoff_leaves_failed_when_retry_exhausted(mock_config: MagicMock) -> None:
    ce = ContextEngine()
    goal = await ce.create_goal("exhausted", max_retries=0)
    await ce.fail_goal(goal.id, error="boom")

    monitor = _monitor(ce, mock_config)
    decision = BackoffDecision(
        backoff_to_goal_id=goal.id,
        reason="no retry left",
        new_directives=[],
        evidence_summary="done",
    )
    await monitor._apply_backoff_decision(decision, failed_goal_id=goal.id)

    after = await ce.get_goal(goal.id)
    assert after is not None
    assert after.status == "failed"


@pytest.mark.asyncio
async def test_recover_failed_goal_resets_send_back() -> None:
    ce = ContextEngine()
    goal = await ce.create_goal("integrate", max_retries=0)
    goal.send_back_count = 3
    goal.max_send_backs = 3
    await ce.fail_goal(goal.id, error="send_back budget exhausted")

    recovered = await ce.recover_failed_goal(goal.id, reason="deadlock", max_engine_recoveries=2)
    assert recovered.status == "pending"
    assert recovered.engine_recovery_count == 1
    assert recovered.send_back_count == 0
    assert recovered.error is None
    texts = [e["text"] for e in recovered.guidance_accumulated]
    assert any("Previous failure: send_back budget exhausted" in t for t in texts)
    assert any("Recovery note: deadlock" in t for t in texts)


@pytest.mark.asyncio
async def test_retry_failed_goal_preserves_error_as_guidance() -> None:
    ce = ContextEngine()
    goal = await ce.create_goal("flaky", max_retries=2)
    await ce.fail_goal(goal.id, error="thin merge evidence")

    retried = await ce.retry_failed_goal(goal.id, reason="backoff retry")
    assert retried.status == "pending"
    assert retried.error is None
    text = retried.guidance_accumulated[-1]["text"]
    assert "Previous failure: thin merge evidence" in text
    assert "Recovery note: backoff retry" in text


@pytest.mark.asyncio
async def test_send_back_attaches_consensus_guidance() -> None:
    ce = ContextEngine()
    goal = await ce.create_goal("integrate", max_send_backs=3)
    ce.claim_goal(goal.id, loop_id="w1")
    updated = await ce.send_back_goal(goal.id, reason="Show actual git merge output")
    assert updated.status == "pending"
    assert updated.guidance_accumulated[-1]["text"] == (
        "Consensus send-back: Show actual git merge output"
    )
    assert updated.guidance_accumulated[-1]["source"] == "consensus_send_back"


@pytest.mark.asyncio
async def test_recover_failed_goal_refuses_rail_root() -> None:
    ce = ContextEngine()
    root = await ce.create_goal("job root", rail_id="greenfield-system")
    await ce.fail_goal(root.id, error="should not happen")
    with pytest.raises(ValueError, match="rail job root"):
        await ce.recover_failed_goal(root.id, reason="nope")


@pytest.mark.asyncio
async def test_health_recovers_failed_blocker(mock_config: MagicMock) -> None:
    ce = ContextEngine()
    root = await ce.create_goal("Task scaffold", priority=80, rail_id="greenfield-system")
    maker = await ce.create_goal("maker", parent_id=root.id, priority=75)
    await ce.complete_goal(maker.id)
    integrate = await ce.create_goal(
        "Integrate wave 1",
        parent_id=root.id,
        priority=78,
        depends_on=[maker.id],
    )
    await ce.fail_goal(integrate.id, error="thin evidence")
    root.depends_on = [integrate.id]

    verifier = GoalDAGVerifier(ce, mock_config)
    report = DagHealthReport(suggest_reset=[integrate.id], reasoning="reset integrate")
    await verifier.apply_health_report(report)

    after = await ce.get_goal(integrate.id)
    assert after is not None
    assert after.status == "pending"
    assert after.engine_recovery_count == 1


@pytest.mark.asyncio
async def test_deadlock_detector_queues_and_recovers(mock_config: MagicMock) -> None:
    ce = ContextEngine()
    root = await ce.create_goal("Task", priority=80, rail_id="greenfield-system")
    maker = await ce.create_goal("maker", parent_id=root.id)
    await ce.complete_goal(maker.id)
    integrate = await ce.create_goal(
        "Integrate",
        parent_id=root.id,
        depends_on=[maker.id],
    )
    await ce.fail_goal(integrate.id, error="failed")
    root.depends_on = [integrate.id]

    verifier = GoalDAGVerifier(ce, mock_config)
    assert verifier.find_deadlocked_failed_goals() == [integrate.id]

    # Heuristic path (no LLM): verify_dag_health merges deadlock + apply recovers.
    async def _boom(_snapshot):  # noqa: ANN001
        raise RuntimeError("llm down")

    verifier._reasoner.verify_health = _boom  # type: ignore[method-assign]
    report = await verifier.verify_dag_health()
    assert integrate.id in report.suggest_reset
    await verifier.apply_health_report(report)

    after = await ce.get_goal(integrate.id)
    assert after is not None
    assert after.status == "pending"


@pytest.mark.asyncio
async def test_engine_recovery_budget_exhaust(mock_config: MagicMock) -> None:
    ce = ContextEngine()
    root = await ce.create_goal("Task", rail_id="greenfield-system")
    maker = await ce.create_goal("maker", parent_id=root.id)
    await ce.complete_goal(maker.id)
    integrate = await ce.create_goal(
        "Integrate",
        parent_id=root.id,
        depends_on=[maker.id],
    )
    integrate.engine_recovery_count = 2
    await ce.fail_goal(integrate.id, error="failed")
    root.depends_on = [integrate.id]

    mock_config.agent.autopilot.max_engine_recoveries = 2
    verifier = GoalDAGVerifier(ce, mock_config)
    assert verifier.find_deadlocked_failed_goals() == []

    report = DagHealthReport(suggest_reset=[integrate.id], reasoning="try again")
    await verifier.apply_health_report(report)
    after = await ce.get_goal(integrate.id)
    assert after is not None
    assert after.status == "failed"


@pytest.mark.asyncio
async def test_health_skips_failed_when_deps_not_completed(mock_config: MagicMock) -> None:
    ce = ContextEngine()
    root = await ce.create_goal("Task", rail_id="greenfield-system")
    maker = await ce.create_goal("maker", parent_id=root.id)
    await ce.fail_goal(maker.id, error="maker failed")
    integrate = await ce.create_goal(
        "Integrate",
        parent_id=root.id,
        depends_on=[maker.id],
    )
    await ce.fail_goal(integrate.id, error="blocked")
    root.depends_on = [integrate.id]

    verifier = GoalDAGVerifier(ce, mock_config)
    assert verifier.find_deadlocked_failed_goals() == []

    report = DagHealthReport(suggest_reset=[integrate.id], reasoning="bad")
    await verifier.apply_health_report(report)
    after = await ce.get_goal(integrate.id)
    assert after is not None
    assert after.status == "failed"
