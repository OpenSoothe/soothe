"""Intent classification Pydantic models (RFC-225, RFC-630).

Intent classification produces a 4-class intake label (RFC-630) —
``chitchat`` | ``trivial`` | ``simple`` | ``complex`` — that drives
``route_by_intent`` branch routing. Whether an agentic query continues an
in-flight loop is derived structurally inside ``StrangeLoop`` from the loaded
checkpoint, not classified here.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field


class IntakeLabel(StrEnum):
    """4-class intake label for branch routing (RFC-630).

    Continuation is NOT a label — it is a structural overlay from the
    checkpoint (RFC-225). The intake LLM never decides continuation.

    - ``chitchat``: small talk (greetings, thanks, casual banter); the intake
      LLM piggybacks ``chitchat_response`` and the runner emits it directly.
    - ``trivial``: trivia, single obvious tool call, or direct answer; pseudo
      1-step plan via execute (no plan_assess/plan_generate).
    - ``simple``: single focused step, lightweight plan.
    - ``complex``: multi-step / multi-phase, full plan.
    """

    CHITCHAT = "chitchat"
    TRIVIAL = "trivial"
    SIMPLE = "simple"
    COMPLEX = "complex"


class TaskComplexity(StrEnum):
    """Unified task complexity levels for routing decisions.

    Used by both IntentClassification and RoutingClassification.
    - minimal: No tools needed (chitchat intake)
    - simple: Single focused step
    - medium: Multi-step with moderate tool use
    - complex: Architecture, migration, deep multi-phase work
    """

    MINIMAL = "minimal"
    SIMPLE = "simple"
    MEDIUM = "medium"
    COMPLEX = "complex"


def derive_task_complexity_from_intake(intake_label: IntakeLabel) -> TaskComplexity:
    """Map intake label to execute-phase task complexity.

    ``task_complexity`` is derived from ``intake_label`` so the intake LLM
    only classifies graph routing; downstream execute tuning reuses the same
    signal without a redundant LLM field.

    Args:
        intake_label: 4-class intake label from the classifier.

    Returns:
        Task complexity for ``RoutingClassification`` and system prompt tiers.
    """
    if intake_label in (IntakeLabel.CHITCHAT, IntakeLabel.TRIVIAL):
        return TaskComplexity.MINIMAL
    if intake_label == IntakeLabel.SIMPLE:
        return TaskComplexity.SIMPLE
    return TaskComplexity.COMPLEX


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
    - ``chitchat``: small talk; ``chitchat_response`` is emitted directly to the client.
    - ``trivial``: direct execute via pseudo 1-step plan (no plan_assess/generate).
    - ``simple``/``complex``: agentic goals of increasing effort; the runner /
      StrangeLoop derive loop continuation structurally from the checkpoint.

    ``intake_label`` drives ``route_by_intent``.

    Args:
        intake_label: 4-class intake label for branch routing (RFC-630).
        reasoning: Brief reasoning for classification (IG-518).
        goal_description: Normalized goal description.
        chitchat_response: Direct reply for ``chitchat`` intake only.
        task_complexity: Routing complexity level (derived from ``intake_label``).
    """

    intake_label: IntakeLabel = Field(
        description="4-class intake label for branch routing: chitchat, trivial, simple, or complex"
    )
    reasoning: str | None = Field(
        default=None,
        description="Brief first-person reasoning (I'll / Let me …).",
    )
    goal_description: str | None = Field(
        default=None,
        description="Normalized goal description for display and GoalEngine",
    )
    chitchat_response: str | None = Field(
        default=None,
        description="Direct friendly reply when intake_label is chitchat",
    )
    task_complexity: TaskComplexity = Field(
        description="Routing complexity derived from intake_label"
    )

    def to_routing_classification(self) -> RoutingClassification:
        """Convert to RoutingClassification for execution path selection."""
        return RoutingClassification(
            task_complexity=self.task_complexity,
            routing_hint="intent_based",
        )


class IntakeClassificationLLMResult(BaseModel):
    """Structured output from the 4-class intake LLM (RFC-630).

    The LLM picks one of ``chitchat``/``trivial``/``simple``/``complex``; the
    label drives ``route_by_intent``. ``chitchat`` carries ``chitchat_response``
    for direct client emission. Other non-trivial labels carry brief
    ``reasoning`` for client visibility (IG-518). Loop continuation is derived
    structurally, not classified.
    """

    intake_label: IntakeLabel = Field(
        description="Primary intake: chitchat (greetings/thanks/casual small talk with "
        "direct reply), trivial (trivia/single obvious action, no planning LLM), "
        "simple (single focused step, lightweight plan), "
        "complex (multi-step/multi-phase, full plan)"
    )
    reasoning: str | None = Field(
        default=None,
        description="One first-person sentence (max 20 words) starting with I'll or Let me; "
        "user-facing next action, never intake-label jargon.",
    )
    goal_description: str | None = Field(
        default=None,
        description="Normalized goal description for display and GoalEngine",
    )
    chitchat_response: str | None = Field(
        default=None,
        description="Required when intake_label is chitchat: friendly direct reply to the user",
    )

    def to_intent_classification(self) -> IntentClassification:
        """Convert LLM result to runtime IntentClassification."""
        task_complexity = derive_task_complexity_from_intake(self.intake_label)
        return IntentClassification(
            intake_label=self.intake_label,
            reasoning=self.reasoning,
            goal_description=self.goal_description,
            chitchat_response=self.chitchat_response,
            task_complexity=task_complexity,
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
