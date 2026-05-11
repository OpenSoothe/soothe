"""Intent classification Pydantic models (IG-226).

Models for LLM-driven query intent classification with three-tier system:
- chitchat: Direct response (no goal)
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

    CHITCHAT = "chitchat"
    QUIZ = "quiz"
    CONTINUE_THREAD = "continue_thread"
    NEW_GOAL = "new_goal"


class TaskComplexity(StrEnum):
    """Unified task complexity levels for routing decisions.

    Used by both IntentClassification and RoutingClassification.
    - minimal: No tools needed (fast-path: chitchat/quiz intents)
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
        chitchat_response: Direct response for chitchat queries.
        preferred_subagent: Wire or classifier hint for which subagent to prefer in AgentLoop.
        routing_hint: Routing strategy hint.
    """

    task_complexity: TaskComplexity = Field(
        description="Routing complexity: minimal (no tools), simple, medium, or complex"
    )
    chitchat_response: str | None = Field(
        default=None,
        description="Direct response for chitchat queries (piggybacked from classification)",
    )
    preferred_subagent: str | None = Field(
        default=None,
        description="Preferred subagent name from slash routing or classifier (e.g. 'browser', 'claude')",
    )
    routing_hint: str | None = Field(
        default=None, description="Routing strategy hint: 'subagent', 'tool', 'llm_only', etc."
    )


class IntentClassification(BaseModel):
    """Primary intent classification model (IG-226, IG-250, IG-287).

    LLM-driven query intent classification determining execution path and goal handling.
    Four-tier classification system with conversation context awareness.

    Args:
        intent_type: Primary intent (chitchat | continue_thread | new_goal | quiz).
        reuse_current_goal: Whether to reuse active goal in current thread.
        goal_description: Normalized goal description for GoalEngine.
        friendly_message: User-friendly reinterpretation for display (IG-287).
        task_complexity: Routing complexity level (minimal | simple | medium | complex).
            For chitchat/quiz intents, task_complexity is always "minimal".
        chitchat_response: Direct response for chitchat queries.
        quiz_response: Direct response for quiz/trivia queries.
        reasoning: LLM reasoning for classification decision.
    """

    intent_type: Literal["chitchat", "continue_thread", "new_goal", "quiz"] = Field(
        description="Primary intent: chitchat (greeting), continue_thread (follow-up), "
        "new_goal (tool-requiring task), quiz (factual knowledge query)"
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
        description="Routing complexity: minimal (chitchat/quiz), simple, medium, or complex"
    )
    chitchat_response: str | None = Field(
        default=None,
        description="Direct response for chitchat queries (piggybacked from classification)",
    )
    quiz_response: str | None = Field(
        default=None,
        description="Direct response for quiz/trivia queries (piggybacked from classification)",
    )
    reasoning: str = Field(description="LLM reasoning explaining classification decision")

    def to_routing_classification(self) -> RoutingClassification:
        """Convert to RoutingClassification for execution path selection.

        Returns:
            RoutingClassification with routing attributes from intent.
        """
        return RoutingClassification(
            task_complexity=self.task_complexity,
            chitchat_response=self.chitchat_response,
            routing_hint="intent_based",
        )


def build_loop_routing_classification(
    intent: IntentClassification | None,
    preferred_subagent: str | None,
) -> RoutingClassification | None:
    """Build routing classification consumed by AgentLoop Plan/Execute.

    Args:
        intent: IntentClassification from classifier.
        preferred_subagent: Optional subagent hint (e.g., 'browser', 'claude').

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

    # intent.task_complexity is already TaskComplexity enum
    base = RoutingClassification(
        task_complexity=intent.task_complexity,
        chitchat_response=intent.chitchat_response,
        preferred_subagent=None,
        routing_hint="intent_based",
    )
    if preferred_subagent:
        return base.model_copy(
            update={"preferred_subagent": preferred_subagent, "routing_hint": "subagent"}
        )
    return base
