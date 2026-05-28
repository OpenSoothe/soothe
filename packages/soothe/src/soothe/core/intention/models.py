"""Intent classification Pydantic models (IG-226).

Models for LLM-driven intent classification with three-tier system:
- quiz: Minimal direct reply (greetings, thanks, trivia) without tools
- continue_thread: Reuse current thread/goal
- new_goal: Create goal via GoalEngine
"""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field


class IntentHint(StrEnum):
    """Suggested intent hint to bypass LLM classification.

    When provided, the classifier may use this hint directly without
    invoking an LLM call, enabling faster routing for known intent types.

    Values match ``IntentClassification.intent_type`` literal values.
    """

    QUIZ = "quiz"
    CONTINUE_THREAD = "continue_thread"
    NEW_GOAL = "new_goal"


class TaskComplexity(StrEnum):
    """Unified task complexity levels for routing decisions.

    Used by both IntentClassification and RoutingClassification.
    - minimal: No tools needed (fast-path: quiz intent)
    - simple: Single focused step
    - medium: Multi-step with moderate tool use
    - complex: Architecture, migration, deep multi-phase work
    """

    MINIMAL = "minimal"
    SIMPLE = "simple"
    MEDIUM = "medium"
    COMPLEX = "complex"


class RoutingClassification(BaseModel):
    """Routing complexity classification for execution path selection.

    Args:
        task_complexity: Routing complexity level.
        preferred_subagent: Wire or classifier hint for which subagent to prefer in AgentLoop.
        routing_hint: Routing strategy hint.
    """

    task_complexity: TaskComplexity = Field(
        description="Routing complexity: minimal (no tools), simple, medium, or complex"
    )
    preferred_subagent: str | None = Field(
        default=None,
        description="Preferred subagent name from slash routing or classifier (e.g. 'explore', 'research')",
    )
    routing_hint: str | None = Field(
        default=None, description="Routing strategy hint: 'subagent', 'tool', 'llm_only', etc."
    )


class IntentClassification(BaseModel):
    """Primary intent classification model (IG-226, IG-250, IG-287).

    LLM-driven query intent classification determining execution path and goal handling.
    Three-tier classification system with conversation context awareness.

    Args:
        intent_type: Primary intent (continue_thread | new_goal | quiz).
        reuse_current_goal: Whether to reuse active goal in current thread.
        goal_description: Normalized goal description for GoalEngine.
        friendly_message: User-friendly reinterpretation for display (IG-287).
        task_complexity: Routing complexity level (minimal | simple | medium | complex).
            For quiz intents, task_complexity is always "minimal".
        quiz_response: Optional direct reply after quiz answer generation (not set by classifier).
    """

    intent_type: Literal["continue_thread", "new_goal", "quiz"] = Field(
        description="Primary intent: quiz (greeting/thanks/trivia without tools), "
        "continue_thread (follow-up), new_goal (tool-requiring task)"
    )
    reuse_current_goal: bool = Field(
        default=False,
        description="Whether to reuse active goal in current thread (continue_thread only)",
    )
    goal_description: str | None = Field(
        default=None, description="Normalized goal description extracted from query (new_goal only)"
    )
    friendly_message: str | None = Field(
        default=None,
        description="User-friendly task reinterpretation for display (new_goal only, IG-287)",
    )
    task_complexity: TaskComplexity = Field(
        description="Routing complexity: minimal (quiz), simple, medium, or complex"
    )
    quiz_response: str | None = Field(
        default=None,
        description="Direct reply for quiz path (set by quiz answer step, not classification)",
    )

    def to_routing_classification(self) -> RoutingClassification:
        """Convert to RoutingClassification for execution path selection.

        Returns:
            RoutingClassification with routing attributes from intent.
        """
        return RoutingClassification(
            task_complexity=self.task_complexity,
            routing_hint="intent_based",
        )


class IntentClassificationLLMResult(BaseModel):
    """Structured output from intent classifier LLM (quiz detection only).

    The LLM decides quiz vs agentic. The runner resolves agentic into
    continue_thread or new_goal based on loop state (structural rule).

    Args:
        intent_type: Primary intent (agentic | quiz).
        goal_description: Normalized goal description for GoalEngine.
        friendly_message: User-friendly reinterpretation for display.
        task_complexity: Routing complexity level.
    """

    intent_type: Literal["agentic", "quiz"] = Field(
        description="Primary intent: quiz (greeting/thanks/static trivia without tools), "
        "agentic (everything else — tools, follow-ups, analysis)"
    )
    goal_description: str | None = Field(
        default=None, description="Normalized goal description extracted from query (agentic only)"
    )
    friendly_message: str | None = Field(
        default=None,
        description="User-friendly task reinterpretation for display (agentic only)",
    )
    task_complexity: TaskComplexity = Field(
        description="Routing complexity: minimal (quiz), simple, medium, or complex"
    )

    def to_intent_classification(self, *, continue_thread: bool) -> IntentClassification:
        """Convert LLM result to runtime IntentClassification.

        Args:
            continue_thread: Whether this is a same-loop continuation (structural decision).

        Returns:
            IntentClassification with quiz_response unset (filled by quiz answer step).
        """
        if self.intent_type == "quiz":
            return IntentClassification(
                intent_type="quiz",
                reuse_current_goal=False,
                goal_description=None,
                friendly_message=None,
                task_complexity=TaskComplexity.MINIMAL,
                quiz_response=None,
            )

        resolved_type = "continue_thread" if continue_thread else "new_goal"
        return IntentClassification(
            intent_type=resolved_type,
            reuse_current_goal=continue_thread,
            goal_description=self.goal_description,
            friendly_message=self.friendly_message,
            task_complexity=self.task_complexity,
            quiz_response=None,
        )


def build_loop_routing_classification(
    intent: IntentClassification | None,
    preferred_subagent: str | None,
) -> RoutingClassification | None:
    """Build routing classification consumed by AgentLoop Plan/Execute.

    Args:
        intent: IntentClassification from classifier.
        preferred_subagent: Optional subagent hint (e.g., 'explore', 'research').

    Returns:
        RoutingClassification for middleware/planner consumption.
    """
    if intent is None:
        if preferred_subagent:
            return RoutingClassification(
                task_complexity=TaskComplexity.MEDIUM,
                preferred_subagent=preferred_subagent,
                routing_hint="subagent",
            )
        return None

    base = RoutingClassification(
        task_complexity=intent.task_complexity,
        preferred_subagent=None,
        routing_hint="intent_based",
    )
    if preferred_subagent:
        return base.model_copy(
            update={"preferred_subagent": preferred_subagent, "routing_hint": "subagent"}
        )
    return base
