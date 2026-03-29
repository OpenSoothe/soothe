"""LLM-based Judge Engine for Layer 2 execution (RFC-0008)."""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from langchain_core.language_models import BaseChatModel

from soothe.cognition.loop_agent.schemas import JudgeResult, StepAction, StepResult

logger = logging.getLogger(__name__)


class LLMJudgeEngine:
    """LLM-based judge implementation for goal progress evaluation.

    This judge uses an LLM to evaluate progress toward goal completion
    based on accumulated evidence from step execution. It supports the
    evidence accumulation model where both successes and errors become
    evidence for evaluation.

    Attributes:
        model: LLM model to use for judgment
    """

    def __init__(self, model: BaseChatModel) -> None:
        """Initialize LLM judge.

        Args:
            model: Chat model for judgment
        """
        self.model = model

    async def judge(
        self,
        goal: str,
        evidence: list[StepResult],
        steps: list[StepAction],
    ) -> JudgeResult:
        """Evaluate goal progress using LLM.

        Args:
            goal: Goal description
            evidence: Results from executed steps
            steps: Steps that were executed

        Returns:
            JudgeResult with status, progress, and reasoning
        """
        # Build evidence summary
        evidence_lines = [result.to_evidence_string() for result in evidence]
        evidence_text = "\n".join(evidence_lines)

        # Count successes and failures
        successes = sum(1 for r in evidence if r.success)
        failures = sum(1 for r in evidence if not r.success)

        # Build prompt
        prompt = f"""Goal: {goal}

Evidence from execution:
{evidence_text}

Summary:
- Steps executed: {len(steps)}
- Successful: {successes}
- Failed: {failures}

Evaluate progress toward the goal:
1. What percentage complete is the goal? (0.0-1.0)
2. Is the goal achieved? (status: "done")
3. Is the current strategy still valid? (status: "continue" vs "replan")
4. What is your confidence in this evaluation? (0.0-1.0)

Consider:
- Successful steps indicate progress toward goal
- Failed steps may indicate wrong approach (need replan)
- Partial progress with valid strategy suggests continue
- Goal fully achieved suggests done
- Errors should be analyzed: are they fatal or recoverable?

Return your evaluation as JSON:
{{
  "status": "continue" | "replan" | "done",
  "goal_progress": 0.0-1.0,
  "confidence": 0.0-1.0,
  "reasoning": "explanation of your evaluation",
  "next_steps_hint": "optional hint for next iteration"
}}
"""

        try:
            response = await self.model.ainvoke(prompt)
            return self._parse_judge_result(response.content)
        except Exception:
            logger.exception("Judge evaluation failed")
            # Return conservative default on error
            return JudgeResult(
                status="replan",
                evidence_summary=evidence_text,
                goal_progress=0.0,
                confidence=0.0,
                reasoning="Judge evaluation failed",
            )

    def _parse_judge_result(self, response: str) -> JudgeResult:
        """Parse LLM response into JudgeResult.

        Args:
            response: LLM response string

        Returns:
            Parsed JudgeResult
        """
        try:
            # Try to parse JSON from response
            # Handle potential markdown code blocks
            if "```json" in response:
                # Extract JSON from markdown code block
                start = response.find("```json") + 7
                end = response.find("```", start)
                json_str = response[start:end].strip()
            elif "```" in response:
                # Extract from generic code block
                start = response.find("```") + 3
                end = response.find("```", start)
                json_str = response[start:end].strip()
            else:
                json_str = response.strip()

            data = json.loads(json_str)

            return JudgeResult(
                status=data.get("status", "replan"),
                evidence_summary=data.get("evidence_summary", ""),
                goal_progress=float(data.get("goal_progress", 0.0)),
                confidence=float(data.get("confidence", 0.5)),
                reasoning=data.get("reasoning", "No reasoning provided"),
                next_steps_hint=data.get("next_steps_hint"),
            )

        except Exception:
            logger.exception("Failed to parse judge result\nResponse: %s", response)
            # Return conservative default
            return JudgeResult(
                status="replan",
                evidence_summary="",
                goal_progress=0.0,
                confidence=0.0,
                reasoning="Failed to parse LLM judgment",
            )
