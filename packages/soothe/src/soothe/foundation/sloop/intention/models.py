"""Intent classification Pydantic models (RFC-225, RFC-630).

Intent classification produces a 4-class intake label (RFC-630) —
``quiz`` | ``trivial`` | ``simple`` | ``complex`` — that drives
``route_by_intent`` branch routing. Whether an agentic query continues an
in-flight loop is derived structurally inside ``StrangeLoop`` from the
loaded checkpoint, not classified here.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field


class IntakeLabel(StrEnum):
    """4-class intake label for branch routing (RFC-630).

    Continuation is NOT a label — it is a structural overlay from the
    checkpoint (RFC-225). The intake LLM never decides continuation.

    - ``quiz``: greeting/thanks/trivia, no tools.
    - ``trivial``: single obvious action, no planning LLM needed.
    - ``simple``: single focused step, lightweight plan.
    - ``complex``: multi-step / multi-phase, full plan.
    """

    QUIZ = "quiz"
    TRIVIAL = "trivial"
    SIMPLE = "simple"
    COMPLEX = "complex"


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
    """Primary intent classification model (RFC-225, IG-518, RFC-630).

    4-class LLM intake classification:
    - ``quiz``: minimal direct reply (greeting/thanks/trivia) without tools.
    - ``trivial``/``simple``/``complex``: agentic goals of increasing effort;
      the runner / StrangeLoop derive loop continuation structurally from the
      checkpoint.

    ``intake_label`` carries the 4-class label and drives ``route_by_intent``;
    ``intent_type`` is derived from it (``quiz`` → ``quiz``, all others →
    ``agentic``) so the downstream quiz fast-path and event emission keep
    working.

    Args:
        intent_type: ``quiz`` or ``agentic`` (derived from ``intake_label``).
        intake_label: 4-class intake label for branch routing (RFC-630).
        reasoning: Brief reasoning for agentic classification (IG-518, agentic only).
        goal_description: Normalized goal description (populated for agentic).
        task_complexity: Routing complexity level.
        quiz_response: Direct quiz answer piggybacked from the LLM (quiz only).
    """

    intent_type: Literal["quiz", "agentic"] = Field(
        description="Primary intent: quiz (greeting/thanks/trivia without tools) or agentic (everything else)"
    )
    intake_label: IntakeLabel = Field(
        description="4-class intake label for branch routing (RFC-630): "
        "quiz, trivial, simple, or complex"
    )
    reasoning: str | None = Field(
        default=None,
        description="Brief first-person reasoning for agentic classification (I'll / Let me …).",
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


class IntakeClassificationLLMResult(BaseModel):
    """Structured output from the 4-class intake LLM (RFC-630).

    The LLM picks one of ``quiz``/``trivial``/``simple``/``complex``; the
    label drives ``route_by_intent``. Quiz piggybacks the answer in
    ``quiz_response`` (preserves the quiz short-circuit). Non-quiz intents
    carry brief ``reasoning`` for client visibility (IG-518). Loop
    continuation is derived structurally, not classified.
    """

    intake_label: IntakeLabel = Field(
        description="Primary intake: quiz (greeting/thanks/trivia, no tools), "
        "trivial (single obvious action, no planning LLM), "
        "simple (single focused step, lightweight plan), "
        "complex (multi-step/multi-phase, full plan)"
    )
    reasoning: str | None = Field(
        default=None,
        description="Brief first-person reasoning (one sentence, max 20 words). Empty for quiz.",
    )
    goal_description: str | None = Field(
        default=None,
        description="Normalized goal description for display and GoalEngine (non-quiz only)",
    )
    task_complexity: TaskComplexity = Field(
        description="Routing complexity: minimal (quiz), simple, medium, or complex"
    )
    quiz_response: str | None = Field(
        default=None,
        description="Direct answer for quiz intents (greeting/thanks/trivia). Concise, from training knowledge.",
    )

    def to_intent_classification(self) -> IntentClassification:
        """Convert LLM result to runtime IntentClassification.

        Maps the 4-class label onto ``intent_type`` so the quiz fast-path and
        event emission keep working: ``quiz`` → ``quiz``, all others →
        ``agentic``. The 4-class label is preserved on ``intake_label`` for
        ``route_by_intent``.
        """
        if self.intake_label == IntakeLabel.QUIZ:
            return IntentClassification(
                intent_type="quiz",
                intake_label=IntakeLabel.QUIZ,
                reasoning=None,
                goal_description=None,
                task_complexity=TaskComplexity.MINIMAL,
                quiz_response=self.quiz_response,
            )
        return IntentClassification(
            intent_type="agentic",
            intake_label=self.intake_label,
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
