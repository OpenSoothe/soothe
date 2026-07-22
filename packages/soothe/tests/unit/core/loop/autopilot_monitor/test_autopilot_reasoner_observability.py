"""Tests that autopilot background reasoners use metadata-only LLM invoke config."""

from __future__ import annotations

import logging
from unittest.mock import AsyncMock, MagicMock

import pytest

from soothe.autopilot.backoff_reasoner import GoalBackoffReasoner
from soothe.autopilot.engine_models import EvidenceBundle
from soothe.context.models import GoalNode

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
async def test_backoff_reasoner_uses_metadata_only_invoke_config(
    mock_config: MagicMock,
) -> None:
    """Backoff reasoning must not register observability callbacks."""
    reasoner = GoalBackoffReasoner(mock_config)
    captured: dict[str, object] = {}

    async def capture_invoke(_messages: object, config: dict | None = None) -> MagicMock:
        captured["config"] = config
        return MagicMock(content=_BACKOFF_JSON)

    reasoner._model = AsyncMock()
    reasoner._model.ainvoke = capture_invoke  # type: ignore[method-assign]

    goals = {
        "failed-1": _goal("failed-1", depends_on=["parent-1"]),
        "parent-1": _goal("parent-1"),
    }
    evidence = EvidenceBundle(
        structured={"error": "timeout"},
        narrative="Execution timed out",
        source="layer2_execute",
    )

    await reasoner.reason_backoff("failed-1", goals, evidence)

    config = captured.get("config")
    assert isinstance(config, dict)
    assert not config.get("callbacks")
    metadata = config.get("metadata")
    assert isinstance(metadata, dict)
    assert metadata.get("soothe_call_purpose") == "backoff_reasoning"


@pytest.mark.asyncio
async def test_backoff_reasoner_logs_decision(
    mock_config: MagicMock,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Backoff reasoning logs structured decision summary."""
    reasoner = GoalBackoffReasoner(mock_config)

    async def mock_ainvoke(_messages: object, config: dict | None = None) -> MagicMock:
        return MagicMock(content=_BACKOFF_JSON)

    reasoner._model = AsyncMock()
    reasoner._model.ainvoke = mock_ainvoke  # type: ignore[method-assign]

    goals = {
        "failed-1": _goal("failed-1", depends_on=["parent-1"]),
        "parent-1": _goal("parent-1"),
    }
    evidence = EvidenceBundle(
        structured={"error": "timeout"},
        narrative="Execution timed out",
        source="layer2_execute",
    )

    with caplog.at_level(logging.INFO):
        await reasoner.reason_backoff("failed-1", goals, evidence)

    assert any("Backoff reasoning" in record.message for record in caplog.records)
    assert any("parent-1" in record.message for record in caplog.records)
