"""Tests that autopilot background reasoners use metadata-only LLM invoke config."""

from __future__ import annotations

import logging
from unittest.mock import AsyncMock, MagicMock

import pytest

from soothe.foundation.autopilot.engine.models import EvidenceBundle
from soothe.foundation.autopilot.monitor.backoff_reasoner import GoalBackoffReasoner
from soothe.foundation.autopilot.monitor.dreaming_reasoner import (
    DreamingDistillationReasoner,
    EpisodicDistillationContext,
)
from soothe.foundation.context.models import GoalNode

_BACKOFF_JSON = """```json
{
  "backoff_to_goal_id": "parent-1",
  "reason": "Dependency assumption failed",
  "new_directives": [{"description": "Fix deps"}],
  "evidence_summary": "Step failed"
}
```"""

_EPISODIC_JSON = """```json
{
  "episodes": [{"goal_id": "g1", "description": "d", "outcome_summary": "ok"}],
  "reasoning": "One episode distilled"
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


@pytest.mark.asyncio
async def test_dreaming_reasoner_uses_metadata_only_invoke_config(
    mock_config: MagicMock,
) -> None:
    """Dreaming distillation must not register observability callbacks."""
    reasoner = DreamingDistillationReasoner(mock_config)
    captured: dict[str, object] = {}

    async def capture_invoke(_messages: object, config: dict | None = None) -> MagicMock:
        captured["config"] = config
        return MagicMock(content=_EPISODIC_JSON)

    reasoner._model = AsyncMock()
    reasoner._model.ainvoke = capture_invoke  # type: ignore[method-assign]

    await reasoner._invoke_llm("prompt", "system prompt")

    config = captured.get("config")
    assert isinstance(config, dict)
    assert not config.get("callbacks")
    metadata = config.get("metadata")
    assert isinstance(metadata, dict)
    assert metadata.get("soothe_call_purpose") == "dreaming_distillation"


@pytest.mark.asyncio
async def test_dreaming_reasoner_logs_episodic_result(
    mock_config: MagicMock,
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Episodic distillation logs structured summary after parsing."""
    reasoner = DreamingDistillationReasoner(mock_config)

    async def mock_invoke_llm(_prompt: str, system_prompt: str = "") -> str:
        return _EPISODIC_JSON

    monkeypatch.setattr(reasoner, "_invoke_llm", mock_invoke_llm)
    monkeypatch.setattr(
        "soothe.foundation.autopilot.monitor.dreaming_reasoner.EPISODIC_DISTILLATION_PROMPT",
        "{goals_detail}\n{ledger_summary}\n{max_episodes}",
    )

    context = EpisodicDistillationContext(goals_detail="g1", ledger_summary="none")
    with caplog.at_level(logging.INFO):
        await reasoner.distill_episodic(context)

    assert any("Dreaming episodic distillation" in record.message for record in caplog.records)
