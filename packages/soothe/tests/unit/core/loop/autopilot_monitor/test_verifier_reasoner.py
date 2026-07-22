"""Tests for DagVerificationReasoner logging and metadata-only invoke config."""

from __future__ import annotations

import logging
from unittest.mock import AsyncMock, MagicMock

import pytest

from soothe.autopilot.verifier_reasoner import (
    DagSnapshot,
    DagVerificationReasoner,
)

_HEALTH_JSON = """```json
{
  "reset_goals": ["g1"],
  "remove_goals": ["g2"],
  "merge_goals": [],
  "decompose_goals": [],
  "priority_adjustments": {"g3": 80},
  "reasoning": "Health check complete"
}
```"""


@pytest.fixture
def mock_config() -> MagicMock:
    """Minimal SootheConfig mock."""
    cfg = MagicMock()
    cfg.agent.autopilot.monitor_model_role = "think"
    cfg.create_chat_model.return_value = AsyncMock()
    return cfg


@pytest.fixture
def reasoner(mock_config: MagicMock) -> DagVerificationReasoner:
    """Reasoner with mocked chat model."""
    r = DagVerificationReasoner(mock_config)
    r._model = AsyncMock()
    return r


@pytest.mark.asyncio
async def test_invoke_llm_uses_metadata_only_invoke_config(
    reasoner: DagVerificationReasoner,
) -> None:
    """DAG verification LLM calls must not register observability callbacks."""
    captured: dict[str, object] = {}

    async def capture_invoke(_messages: object, config: dict | None = None) -> MagicMock:
        captured["config"] = config
        response = MagicMock()
        response.content = "{}"
        return response

    reasoner._model.ainvoke = capture_invoke  # type: ignore[method-assign]

    await reasoner._invoke_llm("prompt", "system", operation="health")

    config = captured.get("config")
    assert isinstance(config, dict)
    assert not config.get("callbacks")
    metadata = config.get("metadata")
    assert isinstance(metadata, dict)
    assert metadata.get("soothe_call_purpose") == "dag_verification"
    assert metadata.get("operation") == "health"


@pytest.mark.asyncio
async def test_verify_health_logs_result(
    reasoner: DagVerificationReasoner,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Health verification logs structured summary after parsing."""
    reasoner._model.ainvoke = AsyncMock(
        return_value=MagicMock(content=_HEALTH_JSON),
    )

    snapshot = DagSnapshot(total_goals=3, active_count=1, pending_count=2)
    with caplog.at_level(logging.INFO):
        await reasoner.verify_health(snapshot)

    assert any("DAG health verification" in record.message for record in caplog.records)
    assert any("Health check complete" in record.message for record in caplog.records)
