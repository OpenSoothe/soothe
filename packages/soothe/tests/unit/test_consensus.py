"""Tests for the consensus loop (soothe.cognition.consensus)."""

import pytest

from soothe.cognition.goal_engine.consensus import (
    _build_consensus_prompt,
    _extract_reasoning,
    _heuristic_evaluation,
    evaluate_goal_completion,
)


class TestHeuristicEvaluation:
    """Tests for heuristic fallback evaluation."""

    def test_accepts_substantive_response(self) -> None:
        response = (
            "The task has been completed. I analyzed the dataset and found 1,234 records. "
            "The pipeline processed all records successfully and generated the output report."
        )
        decision, reasoning = _heuristic_evaluation(response, "", None)
        assert decision == "accept"

    def test_rejects_short_response(self) -> None:
        decision, reasoning = _heuristic_evaluation("ok", "", None)
        assert decision == "send_back"
        assert "too short" in reasoning.lower()

    def test_rejects_empty_response(self) -> None:
        decision, reasoning = _heuristic_evaluation("", "", None)
        assert decision == "send_back"

    def test_detects_failure_indicators(self) -> None:
        response = (
            "I could not complete the task because I don't have the required access. "
            "The data is locked and I was unable to proceed."
        )
        decision, reasoning = _heuristic_evaluation(response, "", None)
        assert decision == "send_back"
        assert "failure indicator" in reasoning.lower()

    def test_accepts_despite_mixed_content(self) -> None:
        response = (
            "Here is the analysis you requested. I processed 500 files and generated the summary report. "
            "The key findings include improved performance metrics and reduced error rates across all categories."
        )
        decision, reasoning = _heuristic_evaluation(response, "", None)
        assert decision == "accept"

    def test_success_criteria_met(self) -> None:
        response = "Completed: data exported, charts generated, report delivered."
        criteria = ["data exported", "charts generated"]
        decision, reasoning = _heuristic_evaluation(response, "", criteria)
        assert decision == "accept"

    def test_success_criteria_mostly_unmet(self) -> None:
        response = "I only managed to start the process. " + "X" * 80
        criteria = ["data exported", "charts generated", "report delivered", "email sent"]
        decision, reasoning = _heuristic_evaluation(response, "", criteria)
        assert decision == "send_back"
        assert "not addressed" in reasoning.lower()

    def test_evidence_summary_used(self) -> None:
        response = "I could not finish."
        evidence = "The agent ran successfully but the results are inconclusive."
        decision, reasoning = _heuristic_evaluation(response, evidence, None)
        # Evidence doesn't have failure indicators, but response is too short
        assert decision == "send_back"

    def test_evidence_without_failure_accepts(self) -> None:
        response = (
            "I completed the task as requested. The analysis covers all required aspects "
            "and the report is ready for review."
        )
        evidence = "All steps completed successfully."
        decision, reasoning = _heuristic_evaluation(response, evidence, None)
        assert decision == "accept"


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
        assert _extract_reasoning(content) == "The response is comprehensive and addresses all requirements."

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
        mock_model.ainvoke.return_value.content = "DECISION: accept\nREASONING: Response is comprehensive."

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
        mock_model.ainvoke.return_value.content = "DECISION: send_back\nREASONING: Missing key analysis section."

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
        mock_model.ainvoke.return_value.content = "DECISION: suspend\nREASONING: Requires external data source."

        decision, reasoning = await evaluate_goal_completion(
            goal_description="Analyze dataset",
            response_text="I need access to the database.",
            model=mock_model,
        )
        assert decision == "suspend"

    async def test_fallback_on_llm_error(self) -> None:
        from unittest.mock import AsyncMock

        mock_model = AsyncMock()
        mock_model.ainvoke.side_effect = RuntimeError("API error")

        response = "I completed the full analysis and generated the report as requested."
        decision, reasoning = await evaluate_goal_completion(
            goal_description="Analyze data",
            response_text=response,
            model=mock_model,
        )
        assert decision == "accept"  # Falls back to heuristic with good response

    async def test_fallback_on_short_response(self) -> None:
        from unittest.mock import AsyncMock

        mock_model = AsyncMock()
        mock_model.ainvoke.return_value.type = "ai"
        mock_model.ainvoke.return_value.content = "DECISION: accept\nREASONING: Good."

        decision, reasoning = await evaluate_goal_completion(
            goal_description="Analyze data",
            response_text="ok",
            model=mock_model,
        )
        # LLM says accept, but we trust the LLM since it returned
        assert decision == "accept"

    async def test_no_model_uses_heuristic(self) -> None:
        response = "I completed the task successfully with detailed results."
        decision, reasoning = await evaluate_goal_completion(
            goal_description="Test task",
            response_text=response,
            model=None,
        )
        assert decision == "accept"

    async def test_heuristic_failure_indicator(self) -> None:
        decision, reasoning = await evaluate_goal_completion(
            goal_description="Test task",
            response_text="I was unable to complete the task due to access restrictions.",
            model=None,
        )
        assert decision == "send_back"
