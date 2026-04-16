"""Goal-Thread Relevance Analysis (RFC-608).

LLM-based semantic analysis to determine if current thread context
hinders next goal execution (goal independence, domain mismatch, pollution).
"""

from __future__ import annotations

import json
import logging
import re
from typing import TYPE_CHECKING

from langchain_core.messages import HumanMessage
from soothe.cognition.agent_loop.checkpoint import (
    AgentLoopCheckpoint,
    GoalExecutionRecord,
    GoalThreadRelevanceAnalysis,
    ThreadSwitchPolicy,
)

if TYPE_CHECKING:
    from langchain_core.language_models import BaseChatModel

logger = logging.getLogger(__name__)

RELEVANCE_PROMPT_TEMPLATE = """Analyze whether the current thread context is relevant to the next goal execution or may hinder goal completion.

**Current Thread Context Summary**:
{thread_summary}

**Thread Goal History**:
{goal_history_text}

**Next Goal**: {next_goal}

**Analysis Criteria**:
Evaluate if the current thread context has any of these hindering factors:

1. **Goal Independence**: Does the next goal have NO connection to the thread's previous work?
   - No dependency on thread's outputs or findings
   - No need to reference or build upon previous context
   - Completely independent task

2. **Context Domain Mismatch**: Does the thread's focus/domain contradict the next goal's needs?
   - Thread focused on different domain (e.g., backend vs frontend)
   - Thread's problem-solving approach inappropriate for next goal
   - Context themes conflict with next goal's requirements

3. **Message History Pollution**: Does the thread contain irrelevant/distracting content?
   - Off-topic tangents unrelated to next goal
   - Clutter that doesn't contribute to next goal
   - Distractions that might mislead execution

**Response Format**:
Provide your analysis as structured JSON:

```json
{
  "is_relevant": true/false,
  "hindering_reasons": ["reason1", "reason2", ...],
  "confidence": 0.0-1.0,
  "reasoning": "detailed explanation of analysis",
  "should_switch_thread": true/false
}
```

**Note**: Failed execution attempts are NOT hindering - they provide valuable learning context. Only switch thread if clear hindering factors detected with confidence >= {confidence_threshold}.
"""


async def analyze_goal_thread_relevance(
    checkpoint: AgentLoopCheckpoint,
    next_goal: str,
    policy: ThreadSwitchPolicy,
    model: "BaseChatModel"
) -> GoalThreadRelevanceAnalysis:
    """LLM-based analysis of goal-thread relevance (RFC-608).

    Args:
        checkpoint: Loop checkpoint with goal history
        next_goal: Next goal to analyze
        policy: Thread switching policy (relevance_confidence_threshold)
        model: LLM model for analysis

    Returns:
        GoalThreadRelevanceAnalysis with hindering detection
    """
    thread_summary = build_thread_summary(checkpoint)
    goal_history_text = format_goal_history(checkpoint.goal_history[-5:])  # Last 5 goals

    analysis_prompt = RELEVANCE_PROMPT_TEMPLATE.format(
        thread_summary=thread_summary,
        goal_history_text=goal_history_text,
        next_goal=next_goal,
        confidence_threshold=policy.relevance_confidence_threshold
    )

    # Call LLM for analysis
    try:
        response = await model.ainvoke([HumanMessage(content=analysis_prompt)])
        analysis_result = parse_llm_analysis_response(response.content)

        # Determine should_switch_thread
        analysis_result.should_switch_thread = (
            not analysis_result.is_relevant
            and analysis_result.confidence >= policy.relevance_confidence_threshold
        )

        logger.info(
            "Goal-thread relevance analysis: is_relevant=%s, confidence=%.2f, switch=%s",
            analysis_result.is_relevant,
            analysis_result.confidence,
            analysis_result.should_switch_thread
        )

        if analysis_result.should_switch_thread:
            logger.info(
                "Hindering factors detected: %s",
                ", ".join(analysis_result.hindering_reasons)
            )

        return analysis_result

    except Exception as e:
        logger.exception("Goal-thread relevance analysis failed")
        # Return fallback analysis (no switch)
        return GoalThreadRelevanceAnalysis(
            thread_summary=thread_summary,
            next_goal=next_goal,
            is_relevant=True,
            hindering_reasons=[],
            confidence=0.0,
            reasoning=f"Analysis failed: {e}",
            should_switch_thread=False
        )


def build_thread_summary(checkpoint: AgentLoopCheckpoint) -> str:
    """Build summary of thread context for relevance analysis.

    Args:
        checkpoint: Loop checkpoint

    Returns:
        Thread summary string with domain focus and recent goals
    """
    if not checkpoint.goal_history:
        return "No previous goals on this thread"

    goal_summaries = [
        f"Goal: {g.goal_text}\nOutcome: {g.status}\nThread: {g.thread_id}"
        for g in checkpoint.goal_history[-5:]
    ]

    thread_domains = extract_thread_domains(checkpoint.goal_history)

    summary = f"Thread Domain Focus: {', '.join(thread_domains)}\n\n" + "\n".join(goal_summaries)

    return summary


def format_goal_history(goal_history: list[GoalExecutionRecord]) -> str:
    """Format goal history for LLM prompt.

    Args:
        goal_history: List of goal execution records

    Returns:
        Formatted goal history string
    """
    formatted = []
    for idx, goal in enumerate(goal_history):
        formatted.append(
            f"- Goal {idx}: {goal.goal_text} → Status: {goal.status}, Thread: {goal.thread_id}"
        )

    return "\n".join(formatted)


def extract_thread_domains(goal_history: list[GoalExecutionRecord]) -> list[str]:
    """Extract domain keywords from goal_history (placeholder).

    Args:
        goal_history: List of goal execution records

    Returns:
        List of detected domain keywords
    """
    # Placeholder: keyword extraction from goal_text
    # Could use NLP or keyword matching in future
    domains = []
    for goal in goal_history:
        # Simple keyword extraction
        text_lower = goal.goal_text.lower()
        if "backend" in text_lower:
            domains.append("backend")
        elif "frontend" in text_lower:
            domains.append("frontend")
        elif "database" in text_lower or "sql" in text_lower:
            domains.append("database")
        elif "api" in text_lower:
            domains.append("api")
        elif "test" in text_lower or "testing" in text_lower:
            domains.append("testing")
        elif "ui" in text_lower or "design" in text_lower:
            domains.append("ui/design")
        elif "debug" in text_lower or "bug" in text_lower:
            domains.append("debugging")

    # Return top 3 unique domains
    unique_domains = list(set(domains))
    return unique_domains[:3] if unique_domains else ["general"]


def parse_llm_analysis_response(response_content: str) -> GoalThreadRelevanceAnalysis:
    """Parse LLM JSON response into GoalThreadRelevanceAnalysis.

    Args:
        response_content: LLM response content (JSON or text)

    Returns:
        GoalThreadRelevanceAnalysis instance
    """
    # Extract JSON from response
    json_match = extract_json_from_response(response_content)

    if json_match:
        try:
            data = json.loads(json_match)

            return GoalThreadRelevanceAnalysis(
                thread_summary="",  # Not needed in response
                next_goal="",  # Not needed
                is_relevant=data.get("is_relevant", True),
                hindering_reasons=data.get("hindering_reasons", []),
                confidence=float(data.get("confidence", 0.0)),
                reasoning=data.get("reasoning", ""),
                should_switch_thread=data.get("should_switch_thread", False)
            )

        except (json.JSONDecodeError, ValueError) as e:
            logger.warning("Failed to parse LLM JSON response: %s", e)

    # Fallback: parse text response
    return parse_text_response_fallback(response_content)


def extract_json_from_response(content: str) -> str | None:
    """Extract JSON block from LLM response.

    Args:
        content: Response content string

    Returns:
        Extracted JSON string or None
    """
    # Try to find JSON code block
    json_pattern = r'```json\s*(.*?)\s*```'
    match = re.search(json_pattern, content, re.DOTALL)

    if match:
        return match.group(1)

    # Try to find raw JSON object
    json_pattern = r'\{[^{}]*"is_relevant"[^{}]*\}'
    match = re.search(json_pattern, content, re.DOTALL)

    if match:
        return match.group(0)

    return None


def parse_text_response_fallback(content: str) -> GoalThreadRelevanceAnalysis:
    """Fallback text parsing if JSON not found.

    Args:
        content: Response content string

    Returns:
        GoalThreadRelevanceAnalysis with low confidence
    """
    # Simple heuristics
    is_relevant = "relevant" in content.lower() and "not" not in content.lower()
    hindering = []

    if "goal independence" in content.lower() or "independent" in content.lower():
        hindering.append("Goal independence")
    if "domain mismatch" in content.lower() or "domain" in content.lower():
        hindering.append("Context domain mismatch")
    if "pollution" in content.lower() or "irrelevant" in content.lower():
        hindering.append("Message history pollution")

    return GoalThreadRelevanceAnalysis(
        thread_summary="",
        next_goal="",
        is_relevant=is_relevant,
        hindering_reasons=hindering,
        confidence=0.5,  # Low confidence for fallback
        reasoning=content[:200],  # Truncate
        should_switch_thread=len(hindering) > 0
    )