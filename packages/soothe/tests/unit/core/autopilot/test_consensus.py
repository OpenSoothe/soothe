"""Tests for the consensus loop (soothe.autopilot.consensus) — IG-678 / IG-690."""

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
        assert "Agent Response:\nResponse text" in prompt
        assert "Agent Response Preview" not in prompt
        assert "accept" in prompt.lower()

    def test_prompt_with_evidence(self) -> None:
        prompt = _build_consensus_prompt("Goal", "Response", "Evidence summary")
        assert "Evidence Summary:\nEvidence summary" in prompt

    def test_prompt_preserves_long_response_and_evidence(self) -> None:
        long_response = "R" * 2000
        long_evidence = "E" * 2000
        prompt = _build_consensus_prompt("Goal", long_response, long_evidence)
        assert long_response in prompt
        assert long_evidence in prompt
        assert "Agent Response Preview" not in prompt
        assert "Agent Response:\n" + long_response in prompt
        assert "Evidence Summary:\n" + long_evidence in prompt

    def test_prompt_includes_instructions(self) -> None:
        prompt = _build_consensus_prompt("Goal", "Response", "")
        assert "send_back" in prompt.lower()
        assert "suspend" in prompt.lower()
        assert "accept" in prompt.lower()
        assert "prefer send_back" in prompt.lower()
        assert "fundamentally blocked" in prompt.lower()


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
