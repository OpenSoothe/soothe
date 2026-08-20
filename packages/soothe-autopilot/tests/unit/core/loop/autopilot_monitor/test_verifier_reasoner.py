"""Tests for DagVerificationReasoner logging and traced invoke config."""

from __future__ import annotations

import logging
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from soothe_autopilot.verify.verifier_reasoner import (
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
async def test_invoke_llm_uses_traced_invoke_config(
    reasoner: DagVerificationReasoner,
) -> None:
    """DAG verification LLM calls go through nano's traced entry point."""
    captured: dict[str, object] = {}

    async def capture_traced(model: object, messages: object, **kwargs: object) -> MagicMock:
        captured["model"] = model
        captured["messages"] = messages
        captured.update(kwargs)
        response = MagicMock()
        response.content = "{}"
        return response

    with patch("soothe_nano.llm.ainvoke_traced", capture_traced):
        await reasoner._invoke_llm("prompt", "system", operation="health")

    assert captured["model"] is reasoner._model
    assert captured["soothe_config"] is reasoner._soothe_config
    assert captured["purpose"] == "dag_verification"
    assert captured["component"] == "autopilot.monitor.verifier_reasoner"
    assert captured["phase"] == "background"
    assert captured["extra_metadata"] == {"operation": "health"}


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
