"""Intent classification Pydantic models (RFC-225, RFC-630).

Intent classification produces a 4-class intake label (RFC-630) —
``chitchat`` | ``trivial`` | ``simple`` | ``complex`` — that drives
``route_by_intent`` branch routing. Whether an agentic query continues an
in-flight loop is derived structurally inside ``StrangeLoop`` from the loaded
checkpoint, not classified here.

The intake LLM emits ``task_complexity`` for agentic goals; ``intake_label``
is derived from that field for the TUI and graph routing. DISPATCH owns
decomposition.

CoreAgent ``TaskComplexity`` / ``RoutingClassification`` are owned by
``soothe_sdk.intention.models`` and re-exported here.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated

from pydantic import BaseModel, Field
from pydantic.json_schema import SkipJsonSchema
from soothe_sdk.intention.models import RoutingClassification, TaskComplexity


class IntakeLabel(StrEnum):
    """4-class intake label for branch routing (RFC-630).

    Continuation is NOT a label — it is a structural overlay from the
    checkpoint (RFC-225). The intake LLM never decides continuation.

    - ``chitchat``: small talk (greetings, thanks, casual banter); the intake
      LLM piggybacks ``chitchat_response`` and the runner emits it directly.
    - ``trivial``: trivia, single obvious tool call, or direct answer; DISPATCH
      grounds a one-step root (no multi-step decomposition).
    - ``simple``: single focused deliverable CoreAgent can finish in one execute.
    - ``complex``: multi-phase / parallel workstreams / durable phase gates.
    """

    CHITCHAT = "chitchat"
    TRIVIAL = "trivial"
    SIMPLE = "simple"
    COMPLEX = "complex"


def derive_task_complexity_from_intake(intake_label: IntakeLabel) -> TaskComplexity:
    """Map a routing label to execute-phase task complexity.

    Used for client-forced ``intake_scope`` and fail-safes where the intake LLM
    did not emit ``task_complexity``.

    Args:
        intake_label: 4-class intake label.

    Returns:
        Task complexity for ``RoutingClassification`` and system prompt tiers.
    """
    if intake_label in (IntakeLabel.CHITCHAT, IntakeLabel.TRIVIAL):
        return TaskComplexity.MINIMAL
    if intake_label == IntakeLabel.SIMPLE:
        return TaskComplexity.SIMPLE
    return TaskComplexity.COMPLEX


def derive_intake_label_from_task_complexity(
    task_complexity: TaskComplexity | None,
) -> IntakeLabel:
    """Map intake LLM ``task_complexity`` to the 4-class routing label.

    The TUI plan panel and ``route_after_preprocess`` read ``intake_label``.
    ``medium`` has no dedicated label and routes as ``complex``.

    Args:
        task_complexity: Execute-phase complexity from intake, or ``None``.

    Returns:
        ``trivial``, ``simple``, or ``complex`` (never ``chitchat``).
    """
    if task_complexity == TaskComplexity.MINIMAL:
        return IntakeLabel.TRIVIAL
    if task_complexity == TaskComplexity.SIMPLE:
        return IntakeLabel.SIMPLE
    return IntakeLabel.COMPLEX


class IntentClassification(BaseModel):
    """Primary intent classification model (RFC-225, RFC-630).

    4-class LLM intake classification:
    - ``chitchat``: small talk; ``chitchat_response`` is emitted directly to the client.
    - ``trivial``: direct execute via DISPATCH root; skips the coverage Eval phase
      and finalizes from the CoreAgent result.
    - ``simple``/``complex``: agentic goals of increasing effort; run the full
      coverage Eval gate; the runner / StrangeLoop derive loop continuation
      structurally from the checkpoint.

    ``intake_label`` drives ``route_by_intent``.

    Args:
        intake_label: 4-class intake label for branch routing (RFC-630).
        reasoning: Brief reasoning for classification.
        chitchat_response: Direct reply for ``chitchat`` intake only.
        task_short_description: Short step-card title for agentic goals.
        task_complexity: Routing complexity level.
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
    task_short_description: str | None = Field(
        default=None,
        description="Short step-card title for agentic goals (from intake classification)",
    )
    response_language: ResponseLanguage | None = Field(
        default=None,
        description="Preferred language for user-facing prose this turn",
    )
    task_complexity: TaskComplexity = Field(
        description="Routing complexity level for execute-phase tuning"
    )


def build_loop_routing_classification(
    intent: IntentClassification | None,
    preferred_subagent: str | None,
) -> RoutingClassification | None:
    """Build routing classification consumed by StrangeLoop Plan/Execute.

    Wired specialists are requested explicitly via slash/daemon ``preferred_subagent``;
    intake never infers one.
    """
    from soothe.sloop.state.schemas import resolve_wire_subagent

    resolved_wire = resolve_wire_subagent(wire_subagent=preferred_subagent)

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
# Intake classification schemas (RFC-630)
# -----------------------------------------------------------------------------


class ResponseLanguage(StrEnum):
    """Primary language for user-facing agent prose (intake detection)."""

    EN = "en"
    ZH = "zh"
    JA = "ja"
    KO = "ko"
    OTHER = "other"


class IntakeConfidence(StrEnum):
    """Confidence level for intake social vs task classification."""

    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class IntakeLLMResult(BaseModel):
    """Structured output from intake classification: social vs task.

    Intake cleanly separates social interactions from work requests. When
    ``is_task=True`` it also emits ``task_complexity`` and a short step-card
    title (``task_short_description``). ``social_response`` is included for the
    fast-path END when ``is_task=False``.

    Args:
        is_task: True if work request, False if social interaction.
        confidence: High/medium/low confidence in the classification.
        social_response: Direct reply when is_task=False (required for chitchat path).
        reasoning: First-person TUI line (work ≤50 words/300 chars, social
            ≤25 words), e.g. "I'll apply the fix.".
        fallback: True when the result came from a fail-safe, not the LLM. Set
            internally only; never part of the wire schema sent to the model.
    """

    is_task: bool = Field(
        description="True if the GOAL is a work request; False if social (greeting, thanks, etc.)"
    )
    confidence: IntakeConfidence = Field(
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
    task_complexity: TaskComplexity | None = Field(
        default=None,
        description=(
            "When is_task=True: task complexity minimal, simple, medium, or complex. "
            "When is_task=False: null."
        ),
    )
    task_short_description: str | None = Field(
        default=None,
        description=(
            "When is_task=True: short step-card title (under ~8 words) summarizing the task. "
            "When is_task=False: null."
        ),
    )
    response_language: ResponseLanguage = Field(
        default=ResponseLanguage.OTHER,
        description=(
            "Primary language for user-facing prose: en, zh, ja, ko, or other when uncertain"
        ),
    )
    reasoning: str = Field(
        description=(
            "First-person TUI cognition line (I will… / Now I will… / Now let me…): "
            "work (is_task=true) ≤50 words or 300 characters; social ≤25 words; "
            "not classification jargon"
        ),
    )
    # Internal only: omitted from wire schema and model_dump so the LLM never sees it.
    fallback: Annotated[bool, SkipJsonSchema()] = Field(
        default=False,
        exclude=True,
        description="Internal: result came from a fail-safe rather than the LLM",
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
    """3-class forced scope (trivial, simple, complex).

    The same values are accepted on ``loop_input.intake_scope`` to skip LLM
    intake classification and force branch routing.
    """

    TRIVIAL = "trivial"
    SIMPLE = "simple"
    COMPLEX = "complex"


def parse_intake_scope(raw: object | None) -> IntakeScope | None:
    """Parse a wire ``intake_scope`` value.

    Args:
        raw: Client value (string or ``None``). Empty / whitespace → ``None``.

    Returns:
        Normalized ``IntakeScope``, or ``None`` when unset.

    Raises:
        ValueError: When ``raw`` is a non-empty string outside trivial|simple|complex,
            or a non-string non-None value.
    """
    if raw is None:
        return None
    if not isinstance(raw, str):
        raise ValueError("intake_scope must be a string (trivial, simple, or complex)")
    text = raw.strip().lower()
    if not text:
        return None
    try:
        return IntakeScope(text)
    except ValueError as exc:
        raise ValueError(f"intake_scope must be trivial, simple, or complex; got {raw!r}") from exc


def intent_classification_from_intake_scope(
    scope: IntakeScope,
    *,
    reasoning: str | None = None,
) -> IntentClassification:
    """Build a forced ``IntentClassification`` from a client ``intake_scope``.

    Implies ``is_task=True`` (skips the social-vs-task classification) and the
    given scope. Continuation remains a structural checkpoint overlay.
    """
    intake_label = IntakeLabel(scope)
    return IntentClassification(
        intake_label=intake_label,
        reasoning=(reasoning or "").strip() or f"Client intake_scope={scope.value}",
        task_complexity=derive_task_complexity_from_intake(intake_label),
    )


def intent_classification_from_intake(
    intake_result: IntakeLLMResult,
) -> IntentClassification:
    """Build task IntentClassification from the intake result.

    ``task_complexity`` and ``task_short_description`` come from the intake
    LLM; ``intake_label`` is derived from that complexity so the TUI and
    graph routing see the same verdict.
    """
    task_complexity = intake_result.task_complexity or TaskComplexity.COMPLEX
    return IntentClassification(
        intake_label=derive_intake_label_from_task_complexity(task_complexity),
        reasoning=intake_result.reasoning,
        chitchat_response=None,
        task_short_description=(intake_result.task_short_description or "").strip() or None,
        response_language=intake_result.response_language,
        task_complexity=task_complexity,
    )
