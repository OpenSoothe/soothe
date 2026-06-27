"""Intent classification Pydantic models (RFC-225).

Two-value intent classification: ``quiz`` (greetings, thanks, trivia
answered without tools) vs. ``agentic`` (everything else). Whether an
agentic query continues an in-flight loop is derived structurally
inside ``StrangeLoop`` from the loaded checkpoint, not classified here.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field


class IntentHint(StrEnum):
    """Suggested intent hint to bypass LLM classification.

    Only ``QUIZ`` is supported — agentic flow is the structural default
    for any non-quiz input and needs no hint.
    """

    QUIZ = "quiz"


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
        preferred_subagent: Wire or classifier hint for which subagent to prefer in StrangeLoop.
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
    """Primary intent classification model (RFC-225, IG-518).

    Two-value LLM classification:
    - ``quiz``: minimal direct reply (greeting/thanks/trivia) without tools.
    - ``agentic``: everything else; the runner / StrangeLoop derive loop
      continuation structurally from the checkpoint.

    Args:
        intent_type: ``quiz`` or ``agentic``.
        reasoning: Brief reasoning for agentic classification (IG-518, agentic only).
        goal_description: Normalized goal description (populated for agentic).
        task_complexity: Routing complexity level.
        quiz_response: Direct quiz answer piggybacked from the LLM (quiz only).
    """

    intent_type: Literal["quiz", "agentic"] = Field(
        description="Primary intent: quiz (greeting/thanks/trivia without tools) or agentic (everything else)"
    )
    reasoning: str | None = Field(
        default=None,
        description="Brief reasoning for agentic classification (why tools/action needed)",
    )
    goal_description: str | None = Field(
        default=None,
        description="Normalized goal description for display and GoalEngine (agentic only)",
    )
    task_complexity: TaskComplexity = Field(
        description="Routing complexity: minimal (quiz), simple, medium, or complex"
    )
    quiz_response: str | None = Field(
        default=None,
        description="Direct quiz answer from classification or quiz answer step",
    )

    def to_routing_classification(self) -> RoutingClassification:
        """Convert to RoutingClassification for execution path selection."""
        return RoutingClassification(
            task_complexity=self.task_complexity,
            routing_hint="intent_based",
        )


class IntentClassificationLLMResult(BaseModel):
    """Structured output from intent classifier LLM (IG-518).

    The LLM decides ``quiz`` vs. ``agentic`` only. Quiz fast-path piggybacks
    the answer in ``quiz_response`` so the runner can short-circuit without
    a second LLM call. Agentic intents include brief ``reasoning`` for
    client visibility (IG-518).
    """

    intent_type: Literal["quiz", "agentic"] = Field(
        description="Primary intent: quiz (greeting/thanks/static trivia without tools), "
        "agentic (everything else — tools, follow-ups, analysis)"
    )
    reasoning: str | None = Field(
        default=None,
        description="Brief reasoning for agentic classification (one sentence max 20 words). Empty for quiz.",
    )
    goal_description: str | None = Field(
        default=None,
        description="Normalized goal description for display and GoalEngine (agentic only)",
    )
    task_complexity: TaskComplexity = Field(
        description="Routing complexity: minimal (quiz), simple, medium, or complex"
    )
    quiz_response: str | None = Field(
        default=None,
        description="Direct answer for quiz intents (greeting/thanks/trivia). Provide concise, factual response from training knowledge.",
    )

    def to_intent_classification(self) -> IntentClassification:
        """Convert LLM result to runtime IntentClassification."""
        if self.intent_type == "quiz":
            return IntentClassification(
                intent_type="quiz",
                reasoning=None,
                goal_description=None,
                task_complexity=TaskComplexity.MINIMAL,
                quiz_response=self.quiz_response,
            )
        return IntentClassification(
            intent_type="agentic",
            reasoning=self.reasoning,
            goal_description=self.goal_description,
            task_complexity=self.task_complexity,
            quiz_response=None,
        )


def build_loop_routing_classification(
    intent: IntentClassification | None,
    preferred_subagent: str | None,
) -> RoutingClassification | None:
    """Build routing classification consumed by StrangeLoop Plan/Execute."""
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
