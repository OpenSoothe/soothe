"""Tests for the consensus loop (soothe_autopilot.verify.consensus) — /."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from soothe_autopilot.prompts import build_consensus_prompt
from soothe_autopilot.verify.consensus import (
    ConsensusEvaluationError,
    ConsensusVerdict,
    evaluate_goal_completion,
)


class TestConsensusPrompt:
    """Tests for consensus prompt builder."""

    def test_basic_prompt(self) -> None:
        prompt = build_consensus_prompt("Test goal", "Response text")
        assert "Test goal" in prompt
        assert "Response text" in prompt
        assert "Goal Report (from ContextEngine):\nResponse text" in prompt
        assert "Agent Response Preview" not in prompt
        assert "Additional report context" not in prompt
        assert "accept" in prompt.lower()

    def test_prompt_preserves_long_goal_report(self) -> None:
        long_response = "R" * 2000
        prompt = build_consensus_prompt("Goal", long_response)
        assert long_response in prompt
        assert "Agent Response Preview" not in prompt
        assert "Goal Report (from ContextEngine):\n" + long_response in prompt

    def test_prompt_includes_instructions(self) -> None:
        prompt = build_consensus_prompt("Goal", "Response")
        assert "send_back" in prompt.lower()
        assert "fail" in prompt.lower()
        assert "suspend" not in prompt.lower()
        assert "accept" in prompt.lower()
        assert "prefer accept" in prompt.lower()
        assert "fundamentally blocked" in prompt.lower()
        assert "evidence_follow_up" not in prompt
        assert "goal report" in prompt.lower()
        assert "dag_ops" in prompt.lower()


@pytest.mark.asyncio
class TestEvaluateGoalCompletion:
    """Tests for structured consensus evaluation."""

    async def test_accept_with_structured_verdict(self) -> None:
        mock_model = MagicMock()
        with patch(
            "soothe_nano.llm.structured.invoke_structured_chat_typed",
            new_callable=AsyncMock,
            return_value=ConsensusVerdict(
                decision="accept", reasoning="Response is comprehensive."
            ),
        ):
            result = await evaluate_goal_completion(
                goal_description="Write a report",
                response_text="I completed the report with all required sections.",
                model=mock_model,
            )
        assert result.decision == "accept"
        assert "comprehensive" in result.reasoning.lower()

    async def test_send_back_with_structured_verdict(self) -> None:
        mock_model = MagicMock()
        with patch(
            "soothe_nano.llm.structured.invoke_structured_chat_typed",
            new_callable=AsyncMock,
            return_value=ConsensusVerdict(
                decision="send_back", reasoning="Missing key analysis section."
            ),
        ):
            result = await evaluate_goal_completion(
                goal_description="Write a report",
                response_text="I started the report.",
                model=mock_model,
            )
        assert result.decision == "send_back"
        assert "missing key analysis" in result.reasoning.lower()

    async def test_fail_with_structured_verdict(self) -> None:
        mock_model = MagicMock()
        with patch(
            "soothe_nano.llm.structured.invoke_structured_chat_typed",
            new_callable=AsyncMock,
            return_value=ConsensusVerdict(decision="fail", reasoning="Needs external credentials."),
        ):
            result = await evaluate_goal_completion(
                goal_description="Deploy to prod",
                response_text="Blocked on secrets.",
                model=mock_model,
            )
        assert result.decision == "fail"
        assert "credentials" in result.reasoning.lower()

    async def test_missing_model_raises(self) -> None:
        with pytest.raises(ConsensusEvaluationError, match="required"):
            await evaluate_goal_completion(
                goal_description="Goal",
                response_text="Response",
                model=None,
            )

    async def test_llm_failure_raises(self) -> None:
        mock_model = MagicMock()
        with (
            patch(
                "soothe_nano.llm.structured.invoke_structured_chat_typed",
                new_callable=AsyncMock,
                side_effect=RuntimeError("boom"),
            ),
            pytest.raises(ConsensusEvaluationError, match="failed"),
        ):
            await evaluate_goal_completion(
                goal_description="Goal",
                response_text="Response",
                model=mock_model,
            )
