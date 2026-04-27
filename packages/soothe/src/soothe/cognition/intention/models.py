"""Intent classification Pydantic models (IG-226).

Models for LLM-driven query intent classification with three-tier system:
- chitchat: Direct response (no goal)
- thread_continuation: Reuse current thread/goal
- new_goal: Create goal via GoalEngine
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class RoutingClassification(BaseModel):
    """Routing complexity classification for execution path selection.

    Args:
        task_complexity: Routing complexity (chitchat | medium | complex).
        chitchat_response: Direct response for chitchat queries.
        preferred_subagent: Preferred subagent name for direct routing.
        routing_hint: Routing strategy hint.
    """

    task_complexity: Literal["chitchat", "medium", "complex"] = Field(
        description="Routing complexity level: chitchat (direct LLM), medium (AgentLoop), complex (multi-step)"
    )
    chitchat_response: str | None = Field(
        default=None,
        description="Direct response for chitchat queries (piggybacked from classification)",
    )
    preferred_subagent: str | None = Field(
        default=None,
        description="Preferred subagent name for direct routing (e.g., 'browser', 'claude')",
    )
    routing_hint: str | None = Field(
        default=None, description="Routing strategy hint: 'subagent', 'tool', 'llm_only', etc."
    )


class IntentClassification(BaseModel):
    """Primary intent classification model (IG-226, IG-250, IG-262).

    LLM-driven query intent classification determining execution path and goal handling.
    Four-tier classification system with conversation context awareness.

    Args:
        intent_type: Primary intent (chitchat | thread_continuation | new_goal | quiz).
        reuse_current_goal: Whether to reuse active goal in current thread.
        goal_description: Normalized goal description for GoalEngine.
        friendly_message: User-friendly reinterpretation for display (IG-262).
        task_complexity: Secondary routing complexity level.
        chitchat_response: Direct response for chitchat queries.
        quiz_response: Direct response for quiz/trivia queries.
        reasoning: LLM reasoning for classification decision.
    """

    intent_type: Literal["chitchat", "thread_continuation", "new_goal", "quiz"] = Field(
        description="Primary intent: chitchat (greeting), thread_continuation (follow-up), "
        "new_goal (tool-requiring task), quiz (factual knowledge query)"
    )
    reuse_current_goal: bool = Field(
        default=False,
        description="Whether to reuse active goal in current thread (thread_continuation only)",
    )
    goal_description: str | None = Field(
        default=None, description="Normalized goal description extracted from query (new_goal only)"
    )
    friendly_message: str | None = Field(
        default=None,
        description="User-friendly task reinterpretation for display (new_goal only, IG-262)",
    )
    task_complexity: Literal["chitchat", "quiz", "medium", "complex"] = Field(
        description="Secondary routing complexity level for execution path refinement"
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
