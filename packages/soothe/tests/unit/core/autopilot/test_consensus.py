"""Tests for the consensus loop (soothe.autopilot.consensus) — IG-678 P0-7."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from soothe.autopilot.consensus import (
    ConsensusEvaluationError,
    ConsensusVerdict,
    _build_consensus_prompt,
    evaluate_goal_completion,
)


class TestConsensusPrompt:
    """Tests for consensus prompt builder."""

    def test_basic_prompt(self) -> None:
        prompt = _build_consensus_prompt("Test goal", "Response text", "")
        assert "Test goal" in prompt
        assert "Response text" in prompt
        assert "accept" in prompt.lower()

    def test_prompt_with_evidence(self) -> None:
        prompt = _build_consensus_prompt("Goal", "Response", "Evidence summary")
        assert "Evidence Summary: Evidence summary" in prompt

    def test_prompt_truncates_long_response(self) -> None:
        long_response = "x" * 1000
        prompt = _build_consensus_prompt("Goal", long_response, "")
        assert len(prompt) < 1000

    def test_prompt_includes_instructions(self) -> None:
        prompt = _build_consensus_prompt("Goal", "Response", "")
        assert "send_back" in prompt.lower()
        assert "suspend" in prompt.lower()
        assert "accept" in prompt.lower()


@pytest.mark.asyncio
class TestEvaluateGoalCompletion:
    """Tests for structured consensus evaluation."""

    async def test_accept_with_structured_verdict(self) -> None:
        mock_model = MagicMock()
        with patch(
            "soothe_nano.utils.llm.structured.invoke_structured_chat_typed",
            new_callable=AsyncMock,
            return_value=ConsensusVerdict(
                decision="accept", reasoning="Response is comprehensive."
            ),
        ):
            decision, reasoning = await evaluate_goal_completion(
                goal_description="Write a report",
                response_text="I completed the report with all required sections.",
                model=mock_model,
            )
        assert decision == "accept"
        assert "comprehensive" in reasoning.lower()

    async def test_send_back_with_structured_verdict(self) -> None:
        mock_model = MagicMock()
        with patch(
            "soothe_nano.utils.llm.structured.invoke_structured_chat_typed",
            new_callable=AsyncMock,
            return_value=ConsensusVerdict(
                decision="send_back", reasoning="Missing key analysis section."
            ),
        ):
            decision, reasoning = await evaluate_goal_completion(
                goal_description="Write a report",
                response_text="I started the report.",
                model=mock_model,
            )
        assert decision == "send_back"
        assert "missing key analysis" in reasoning.lower()

    async def test_suspend_with_structured_verdict(self) -> None:
        mock_model = MagicMock()
        with patch(
            "soothe_nano.utils.llm.structured.invoke_structured_chat_typed",
            new_callable=AsyncMock,
            return_value=ConsensusVerdict(
                decision="suspend", reasoning="Needs external credentials."
            ),
        ):
            decision, reasoning = await evaluate_goal_completion(
                goal_description="Deploy to prod",
                response_text="Blocked on secrets.",
                model=mock_model,
            )
        assert decision == "suspend"
        assert "credentials" in reasoning.lower()

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
                "soothe_nano.utils.llm.structured.invoke_structured_chat_typed",
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
