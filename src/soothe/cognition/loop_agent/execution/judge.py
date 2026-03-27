"""LLM-based judgment engine for LoopAgent.

Implements the JUDGE phase with structured output, replacing text pattern matching.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from langchain_core.language_models import BaseChatModel

    from soothe.cognition.loop_agent.core.schemas import (
        AgentDecision,
        JudgeResult,
        ToolOutput,
    )
    from soothe.cognition.loop_agent.core.state import LoopState


logger = logging.getLogger(__name__)


# Judge prompt template
JUDGE_PROMPT_TEMPLATE = """You are the judge for an agent's action.

Goal: {goal}

Action taken: {decision}

Result: {result}

Evaluate the result and decide what to do next.

Instructions:
1. Did the tool succeed? Check if the tool executed without errors.
2. Is the goal achieved? Consider if the task is complete.
3. What action is needed? Choose one:
   - "continue": Keep working on the goal (more steps needed)
   - "retry": Retry the current step with adjustments
   - "replan": Need to change the overall approach
   - "done": Task is complete

Output a JSON object with:
- status: "continue" | "retry" | "replan" | "done"
- reason: Brief explanation (1-2 sentences)
- next_hint: (optional) Suggestion for retry
- final_answer: (if done) The final answer
- confidence: 0.0-1.0

Examples:

For successful completion:
{{"status": "done", "reason": "Found the answer", "final_answer": "42 lines", "confidence": 0.95}}

For needing more work:
{{"status": "continue", "reason": "Partial result, need to verify", "confidence": 0.7}}

For tool failure:
{{"status": "retry", "reason": "File not found, try different path",
  "next_hint": "Check if file exists", "confidence": 0.6}}
"""


class JudgeEngine:
    """LLM-based judgment engine.

    Evaluates tool execution results and decides next action
    using structured output instead of text pattern matching.
    """

    def __init__(self, model: BaseChatModel) -> None:
        """Initialize judge engine.

        Args:
            model: LangChain chat model with structured output support
        """
        self.model = model

    async def judge(
        self,
        loop_state: LoopState,
        decision: AgentDecision,
        result: ToolOutput,
    ) -> JudgeResult:
        """Execute judgment on tool execution result.

        Args:
            loop_state: Current loop state
            decision: Decision that led to tool execution
            result: Tool execution result

        Returns:
            Structured JudgeResult
        """
        # Import here to avoid circular dependency
        from soothe.cognition.loop_agent.core.schemas import JudgeResult

        # Build prompt
        prompt = JUDGE_PROMPT_TEMPLATE.format(
            goal=loop_state.goal,
            decision=decision.model_dump(),
            result=result.model_dump(),
        )

        try:
            # Get structured output from LLM
            structured_model = self.model.with_structured_output(JudgeResult)
            judgment = await structured_model.ainvoke(prompt)
        except Exception:
            logger.exception("Judgment failed")

            # Fallback: return continue status
            return JudgeResult(
                status="continue",
                reason="Judgment failed",
                confidence=0.0,
            )
        else:
            logger.debug("Judgment: status=%s, confidence=%s", judgment.status, judgment.confidence)
            return judgment
