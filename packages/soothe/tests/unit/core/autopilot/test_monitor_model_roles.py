"""Tests for AutopilotConfig monitor and consensus model role wiring."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from soothe.autopilot.backoff_reasoner import GoalBackoffReasoner
from soothe.autopilot.dreaming_reasoner import DreamingDistillationReasoner
from soothe.autopilot.verifier_reasoner import DagVerificationReasoner
from soothe.config import SootheConfig


def test_autopilot_model_role_defaults() -> None:
    cfg = SootheConfig()
    assert cfg.agent.autopilot.monitor_model_role == "think"
    assert cfg.agent.autopilot.consensus_model_role == "think"


def test_autopilot_model_role_yaml_override() -> None:
    cfg = SootheConfig(
        agent={
            "autopilot": {
                "monitor_model_role": "fast",
                "consensus_model_role": "default",
            }
        }
    )
    assert cfg.agent.autopilot.monitor_model_role == "fast"
    assert cfg.agent.autopilot.consensus_model_role == "default"


def test_monitor_reasoners_use_monitor_model_role() -> None:
    cfg = SootheConfig(
        agent={"autopilot": {"monitor_model_role": "fast"}},
    )
    fast_model = MagicMock(name="fast-model")

    with patch.object(SootheConfig, "create_chat_model", return_value=fast_model) as create_model:
        backoff = GoalBackoffReasoner(cfg)
        dreaming = DreamingDistillationReasoner(cfg)
        verifier = DagVerificationReasoner(cfg)

    assert create_model.call_count == 3
    for call in create_model.call_args_list:
        assert call.args[0] == "fast"
    assert backoff._model is fast_model
    assert dreaming._model is fast_model
    assert verifier._model is fast_model
