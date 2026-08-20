"""Tests that Autopilot background reasoners use traced LLM invocation."""

from __future__ import annotations

import logging
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from soothe.context.models import GoalNode
from soothe.goal_contracts import EvidenceBundle

from soothe_autopilot.verify.backoff_reasoner import GoalBackoffReasoner


def _fake_projector() -> MagicMock:
    """Projector mock returning an empty ancestor transcript."""
    proj = MagicMock()
    proj.build_preamble_text = AsyncMock(return_value="")
    return proj


_BACKOFF_JSON = """```json
{
  "backoff_to_goal_id": "parent-1",
  "reason": "Dependency assumption failed",
  "new_directives": [{"description": "Fix deps"}],
  "evidence_summary": "Step failed"
}
```"""


def _goal(goal_id: str, *, depends_on: list[str] | None = None) -> MagicMock:
    goal = MagicMock(spec=GoalNode)
    goal.id = goal_id
    goal.description = f"Goal {goal_id}"
    goal.status = "failed" if goal_id == "failed-1" else "pending"
    goal.priority = 50
    goal.depends_on = depends_on or []
    goal.conflicts_with = []
    return goal


@pytest.fixture
def mock_config() -> MagicMock:
    cfg = MagicMock()
    cfg.agent.autopilot.monitor_model_role = "think"
    cfg.create_chat_model.return_value = AsyncMock()
    return cfg


@pytest.mark.asyncio
async def test_backoff_reasoner_uses_traced_invoke_interface(
    mock_config: MagicMock,
) -> None:
    """Backoff reasoning forwards process config to nano tracing."""
    reasoner = GoalBackoffReasoner(mock_config)
    traced = AsyncMock(return_value=MagicMock(content=_BACKOFF_JSON))

    goals = {
        "failed-1": _goal("failed-1", depends_on=["parent-1"]),
        "parent-1": _goal("parent-1"),
    }
    evidence = EvidenceBundle(
        structured={"error": "timeout"},
        narrative="Execution timed out",
        source="layer2_execute",
    )

    with patch("soothe_nano.llm.ainvoke_traced", traced):
        await reasoner.reason_backoff("failed-1", goals, evidence, projector=_fake_projector())

    kwargs = traced.await_args.kwargs
    assert kwargs["soothe_config"] is mock_config
    assert kwargs["purpose"] == "backoff_reasoning"
    assert kwargs["component"] == "autopilot.backoff_reasoner"


@pytest.mark.asyncio
async def test_backoff_reasoner_logs_decision(
    mock_config: MagicMock,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Backoff reasoning logs structured decision summary."""
    reasoner = GoalBackoffReasoner(mock_config)
    traced = AsyncMock(return_value=MagicMock(content=_BACKOFF_JSON))

    goals = {
        "failed-1": _goal("failed-1", depends_on=["parent-1"]),
        "parent-1": _goal("parent-1"),
    }
    evidence = EvidenceBundle(
        structured={"error": "timeout"},
        narrative="Execution timed out",
        source="layer2_execute",
    )

    with (
        patch("soothe_nano.llm.ainvoke_traced", traced),
        caplog.at_level(logging.INFO),
    ):
        await reasoner.reason_backoff("failed-1", goals, evidence, projector=_fake_projector())

    assert any("Backoff reasoning" in record.message for record in caplog.records)
    assert any("parent-1" in record.message for record in caplog.records)
