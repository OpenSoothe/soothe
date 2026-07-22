"""Intent classification Pydantic models (RFC-225, RFC-630).

Intent classification produces a 4-class intake label (RFC-630) —
``chitchat`` | ``trivial`` | ``simple`` | ``complex`` — that drives
``route_by_intent`` branch routing. Whether an agentic query continues an
in-flight loop is derived structurally inside ``StrangeLoop`` from the loaded
checkpoint, not classified here.

Two-pass intake (RFC-630 IG-554): Pass 1 (social vs task) → Pass 2 (scope).
Pass 1 returns ``is_task`` boolean; Pass 2 returns ``scope`` for work requests.

CoreAgent ``TaskComplexity`` / ``RoutingClassification`` are owned by
``soothe_sdk.intention.models`` and re-exported here.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field
from soothe_sdk.intention.models import RoutingClassification, TaskComplexity


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
    chitchat_response: str | None = Field(
        default=None,
        description="Direct friendly reply when intake_label is chitchat",
    )
    social_kind: IntakePass1SocialKind | None = Field(
        default=None,
        description="Pass 1 social sub-kind when intake_label is chitchat",
    )
    multi_phase: bool = Field(
        default=False,
        description="Pass 2: goal implies multiple ordered execution phases",
    )
    wire_subagent: str | None = Field(
        default=None,
        description=(
            "Pass 2: wired specialist when primary intent is to call one "
            "(planner, browser_use, deep_research, academic_research)"
        ),
    )
    requires_tool_use: bool = Field(
        default=False,
        description=(
            "Pass 2: true when answering requires external/live data or tool execution "
            "(weather, web lookup, file contents); false for pure reasoning/math."
        ),
    )
    response_language: ResponseLanguage | None = Field(
        default=None,
        description="Pass 1: preferred language for user-facing prose this turn",
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


def build_loop_routing_classification(
    intent: IntentClassification | None,
    preferred_subagent: str | None,
) -> RoutingClassification | None:
    """Build routing classification consumed by StrangeLoop Plan/Execute.

    Prefers slash/daemon ``preferred_subagent``, then Pass 2 ``wire_subagent``.
    """
    from soothe.sloop.state.schemas import resolve_wire_subagent

    slash_wire = resolve_wire_subagent(wire_subagent=preferred_subagent)
    pass2_wire = None
    if intent is not None:
        pass2_wire = resolve_wire_subagent(wire_subagent=getattr(intent, "wire_subagent", None))
    resolved_wire = slash_wire or pass2_wire

    if intent is None:
        if resolved_wire:
            return RoutingClassification(
                task_complexity=TaskComplexity.MEDIUM,
                preferred_subagent=resolved_wire,
                routing_hint="subagent",
            )
        return None

    base = RoutingClassification(
        task_complexity=intent.task_complexity,
        preferred_subagent=None,
        routing_hint="intent_based",
    )
    if resolved_wire:
        return base.model_copy(
            update={"preferred_subagent": resolved_wire, "routing_hint": "subagent"}
        )
    return base


# -----------------------------------------------------------------------------
# Two-pass intake schemas (RFC-630, IG-554)
# -----------------------------------------------------------------------------


class ResponseLanguage(StrEnum):
    """Primary language for user-facing agent prose (Pass 1 detection)."""

    EN = "en"
    ZH = "zh"
    JA = "ja"
    KO = "ko"
    OTHER = "other"


class IntakePass1Confidence(StrEnum):
    """Confidence level for Pass 1 social vs task classification."""

    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class IntakePass1SocialKind(StrEnum):
    """Social sub-kind from Pass 1 (RFC-630 heuristic migration)."""

    GREETING = "greeting"
    THANKS = "thanks"
    IDENTITY = "identity"
    DATETIME = "datetime"
    BANTER = "banter"
    OTHER = "other"


class IntakePass1LLMResult(BaseModel):
    """Structured output from Pass 1: social vs task (RFC-630 IG-554).

    Pass 1 cleanly separates social interactions from work requests. No prior
    context is provided — the decision depends only on GOAL text. ``social_response``
    is included for fast-path END when ``is_task=False``.

    Args:
        is_task: True if work request, False if social interaction.
        confidence: High/medium/low confidence in the classification.
        social_response: Direct reply when is_task=False (required for chitchat path).
        reasoning: Brief reasoning (≤15 words).
    """

    is_task: bool = Field(
        description="True if the GOAL is a work request; False if social (greeting, thanks, etc.)"
    )
    confidence: IntakePass1Confidence = Field(
        description="Confidence in the classification: high, medium, or low"
    )
    social_response: str | None = Field(
        default=None,
        description=(
            "Required when is_task=False: friendly direct reply to the user. "
            "For identity: name the configured assistant and Dr. Xiaming Chen; "
            "never Claude, ChatGPT, Gemini, or other vendor models."
        ),
    )
    social_kind: IntakePass1SocialKind = Field(
        default=IntakePass1SocialKind.OTHER,
        description=(
            "When is_task=False: greeting, thanks, identity, datetime, banter, or other. "
            "When is_task=True: other."
        ),
    )
    response_language: ResponseLanguage = Field(
        default=ResponseLanguage.OTHER,
        description=(
            "Primary language for user-facing prose: en, zh, ja, ko, or other when uncertain"
        ),
    )
    reasoning: str = Field(
        description="Brief reasoning for the classification (≤15 words)",
    )


def normalize_response_language(value: object | None) -> ResponseLanguage | None:
    """Coerce wire values to ``ResponseLanguage``; unknown values become ``other``."""
    if value is None:
        return None
    if isinstance(value, ResponseLanguage):
        return value
    text = str(value).strip().lower()
    if not text:
        return None
    try:
        return ResponseLanguage(text)
    except ValueError:
        return ResponseLanguage.OTHER


class IntakeScope(StrEnum):
    """3-class scope for Pass 2 classification (trivial, simple, complex).

    Pass 2 only runs when Pass 1 returns ``is_task=True``. The ``chitchat`` label
    is not an option — Pass 1 already decided social vs task.
    """

    TRIVIAL = "trivial"
    SIMPLE = "simple"
    COMPLEX = "complex"


class IntakePass2LLMResult(BaseModel):
    """Structured output from Pass 2: scope classification (RFC-630 IG-554).

    Pass 2 classifies work scope as trivial, simple, or complex. Prior-goal
    projection is included for reference resolution ("apply it"). The model
    does not see ``chitchat`` as an option — Pass 1 already decided social vs task.

    Args:
        scope: Work scope: trivial (single action), simple (focused step), complex (multi-step).
        reasoning: First-person TUI line (I'll / Let me …), ≤15 words.
    """

    scope: IntakeScope = Field(
        description="Work scope: trivial (single action, no planning), "
        "simple (focused step, light planning), complex (multi-step, full plan)"
    )
    reasoning: str = Field(
        description=(
            "First-person agent line for the TUI cognition card (I'll / Let me …), "
            "≤15 words; not third-person scope commentary"
        ),
    )
    multi_phase: bool = Field(
        default=False,
        description="True when the goal implies multiple ordered execution phases",
    )
    wire_subagent: str | None = Field(
        default=None,
        description=(
            "Wired specialist when primary intent is to call one: planner, "
            "browser_use, deep_research, academic_research, or null"
        ),
    )
    requires_tool_use: bool = Field(
        default=False,
        description=(
            "True when answering requires external/live data or tool execution "
            "(weather, web lookup, file contents). False for pure reasoning/math."
        ),
    )

    def to_intake_label(self) -> IntakeLabel:
        """Convert scope to IntakeLabel for routing."""
        return IntakeLabel(self.scope)
