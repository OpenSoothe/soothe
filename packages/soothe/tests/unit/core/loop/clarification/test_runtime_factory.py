"""Unit tests for the runtime clarification-policy factory (RFC-622, IG-462)."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from soothe.core.loop.clarification.auto import AutoClarificationPolicy
from soothe.core.loop.clarification.interactive import InteractiveClarificationPolicy
from soothe.core.loop.clarification.runtime_factory import (
    build_clarification_policy_for_runner,
    resolve_clarification_mode,
)


def _make_config(default_mode: str = "auto") -> Any:
    """Construct a minimal config stub with the fields the factory reads."""
    cfg = MagicMock()
    cfg.agent.clarification.default_mode = default_mode
    cfg.agent.clarification.auto_min_confidence = 0.4
    cfg.agent.veritas.model_role = "think"
    cfg.agent.veritas.max_context_steps = 8
    cfg.create_chat_model = MagicMock(return_value=MagicMock())
    return cfg


class TestResolveClarificationMode:
    def test_explicit_auto_overrides_config(self) -> None:
        assert resolve_clarification_mode("auto", _make_config("manual")) == "auto"

    def test_explicit_manual_overrides_config(self) -> None:
        assert resolve_clarification_mode("manual", _make_config("auto")) == "manual"

    def test_none_falls_back_to_config_default(self) -> None:
        assert resolve_clarification_mode(None, _make_config("manual")) == "manual"

    def test_blank_falls_back_to_config_default(self) -> None:
        assert resolve_clarification_mode("   ", _make_config("auto")) == "auto"

    def test_unknown_value_falls_back_to_config_default(self) -> None:
        assert resolve_clarification_mode("turbo", _make_config("auto")) == "auto"

    def test_case_insensitive(self) -> None:
        assert resolve_clarification_mode("AUTO", _make_config("manual")) == "auto"
        assert resolve_clarification_mode("Manual", _make_config("auto")) == "manual"


class TestBuildClarificationPolicyForRunner:
    def test_auto_mode_returns_auto_policy(self) -> None:
        config = _make_config()
        policy = build_clarification_policy_for_runner(config, mode="auto")
        assert isinstance(policy, AutoClarificationPolicy)

    def test_manual_mode_returns_interactive_policy(self) -> None:
        config = _make_config()
        policy = build_clarification_policy_for_runner(config, mode="manual")
        assert isinstance(policy, InteractiveClarificationPolicy)

    def test_none_mode_uses_config_default(self) -> None:
        config = _make_config(default_mode="manual")
        policy = build_clarification_policy_for_runner(config, mode=None)
        assert isinstance(policy, InteractiveClarificationPolicy)

    def test_auto_policy_uses_configured_min_confidence(self) -> None:
        config = _make_config()
        config.agent.clarification.auto_min_confidence = 0.66
        policy = build_clarification_policy_for_runner(config, mode="auto")
        assert isinstance(policy, AutoClarificationPolicy)
        assert policy.min_confidence == pytest.approx(0.66)

    def test_veritas_model_built_with_configured_role(self) -> None:
        config = _make_config()
        config.agent.veritas.model_role = "fast"
        build_clarification_policy_for_runner(config, mode="auto")
        config.create_chat_model.assert_called_once_with("fast")

    def test_manual_mode_does_not_build_veritas_model(self) -> None:
        config = _make_config()
        build_clarification_policy_for_runner(config, mode="manual")
        config.create_chat_model.assert_not_called()

    @pytest.mark.asyncio
    async def test_auto_policy_invokes_veritas_with_configured_steps(self) -> None:
        from soothe.subagents.veritas.schemas import VeritasAnswerSchema

        config = _make_config()
        config.agent.veritas.max_context_steps = 3

        with patch("soothe.core.loop.clarification.runtime_factory.veritas_answer") as mock_answer:
            mock_answer.return_value = VeritasAnswerSchema(
                answers=["ok"], confidence=0.9, defer=False
            )
            policy = build_clarification_policy_for_runner(config, mode="auto")
            assert isinstance(policy, AutoClarificationPolicy)
            stub_request = MagicMock(questions=("Q?",))
            # AutoClarificationPolicy.answer awaits the closure.
            await policy._veritas_answer(stub_request)  # noqa: SLF001
            mock_answer.assert_called_once()
            kwargs = mock_answer.call_args.kwargs
            assert kwargs["max_context_steps"] == 3
