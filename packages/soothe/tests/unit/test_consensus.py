"""Tests for the consensus loop (soothe.cognition.consensus)."""

import pytest

from soothe.foundation.autopilot.engine.consensus import (
    ConsensusEvaluationError,
    _build_consensus_prompt,
    _extract_reasoning,
    evaluate_goal_completion,
)


class TestConsensusPrompt:
    """Tests for consensus prompt builder."""

    def test_basic_prompt(self) -> None:
        prompt = _build_consensus_prompt("Test goal", "Response text", "", None)
        assert "Test goal" in prompt
        assert "Response text" in prompt
        assert "DECISION:" in prompt

    def test_prompt_with_evidence(self) -> None:
        prompt = _build_consensus_prompt("Goal", "Response", "Evidence summary", None)
        assert "Evidence Summary: Evidence summary" in prompt

    def test_prompt_with_criteria(self) -> None:
        criteria = ["Export data", "Generate report"]
        prompt = _build_consensus_prompt("Goal", "Response", "Evidence", criteria)
        assert "Export data" in prompt
        assert "Generate report" in prompt

    def test_prompt_truncates_long_response(self) -> None:
        long_response = "x" * 1000
        prompt = _build_consensus_prompt("Goal", long_response, "", None)
        assert len(prompt) < 1000

    def test_prompt_includes_instructions(self) -> None:
        prompt = _build_consensus_prompt("Goal", "Response", "", None)
        assert "send_back" in prompt.lower()
        assert "suspend" in prompt.lower()
        assert "accept" in prompt.lower()


class TestExtractReasoning:
    """Tests for reasoning extraction from LLM responses."""

    def test_extracts_reasoning_line(self) -> None:
        content = "DECISION: accept\nREASONING: The response is comprehensive and addresses all requirements."
        assert (
            _extract_reasoning(content)
            == "The response is comprehensive and addresses all requirements."
        )

    def test_returns_content_if_no_reasoning(self) -> None:
        content = "The agent completed the task successfully."
        result = _extract_reasoning(content)
        assert len(result) <= 200

    def test_handles_multiline_response(self) -> None:
        content = "DECISION: send_back\nREASONING: Missing key deliverable: the final report.\nAdditional notes here."
        result = _extract_reasoning(content)
        assert "Missing key deliverable" in result

    def test_case_insensitive_reasoning_prefix(self) -> None:
        content = "decision: accept\nreasoning: All criteria met."
        result = _extract_reasoning(content)
        assert "All criteria met" in result

    def test_truncates_long_content(self) -> None:
        content = "x" * 500
        result = _extract_reasoning(content)
        assert len(result) <= 200


@pytest.mark.asyncio
class TestEvaluateGoalCompletion:
    """Tests for the main async evaluation function."""

    async def test_accept_with_good_response_and_model(self) -> None:
        from unittest.mock import AsyncMock

        mock_model = AsyncMock()
        mock_model.ainvoke.return_value.type = "ai"
        mock_model.ainvoke.return_value.content = (
            "DECISION: accept\nREASONING: Response is comprehensive."
        )

        decision, reasoning = await evaluate_goal_completion(
            goal_description="Write a report",
            response_text="I completed the report with all required sections.",
            model=mock_model,
        )
        assert decision == "accept"

    async def test_send_back_with_model(self) -> None:
        from unittest.mock import AsyncMock

        mock_model = AsyncMock()
        mock_model.ainvoke.return_value.type = "ai"
        mock_model.ainvoke.return_value.content = (
            "DECISION: send_back\nREASONING: Missing key analysis section."
        )

        decision, reasoning = await evaluate_goal_completion(
            goal_description="Write a report",
            response_text="I started the report.",
            model=mock_model,
        )
        assert decision == "send_back"
        assert "missing key analysis" in reasoning.lower()

    async def test_suspend_with_model(self) -> None:
        from unittest.mock import AsyncMock

        mock_model = AsyncMock()
        mock_model.ainvoke.return_value.type = "ai"
        mock_model.ainvoke.return_value.content = (
            "DECISION: suspend\nREASONING: Requires external data source."
        )

        decision, reasoning = await evaluate_goal_completion(
            goal_description="Analyze dataset",
            response_text="I need access to the database.",
            model=mock_model,
        )
        assert decision == "suspend"

    async def test_raises_on_llm_error(self) -> None:
        from unittest.mock import AsyncMock

        mock_model = AsyncMock()
        mock_model.ainvoke.side_effect = RuntimeError("API error")

        with pytest.raises(ConsensusEvaluationError, match="Consensus LLM evaluation failed"):
            await evaluate_goal_completion(
                goal_description="Analyze data",
                response_text="I completed the full analysis and generated the report.",
                model=mock_model,
            )

    async def test_trusts_llm_accept_decision(self) -> None:
        from unittest.mock import AsyncMock

        mock_model = AsyncMock()
        mock_model.ainvoke.return_value.type = "ai"
        mock_model.ainvoke.return_value.content = "DECISION: accept\nREASONING: Good."

        decision, reasoning = await evaluate_goal_completion(
            goal_description="Analyze data",
            response_text="ok",
            model=mock_model,
        )
        assert decision == "accept"

    async def test_no_model_raises(self) -> None:
        with pytest.raises(ConsensusEvaluationError, match="Consensus model is required"):
            await evaluate_goal_completion(
                goal_description="Test task",
                response_text="I completed the task successfully with detailed results.",
                model=None,
            )
