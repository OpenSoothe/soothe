"""Auto-mode clarification policy backed by the veritas subagent."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable, Collection

from soothe.sloop.clarification.protocol import (
    ClarificationAnswer,
    ClarificationDeferredError,
    ClarificationOrigin,
    ClarificationPolicy,
    ClarificationRequest,
    DeferKind,
)
from soothe.sloop.clarification.tool_approval_pipeline import (
    ToolApprovalPipeline,
)
from soothe.subagents.veritas.schemas import VeritasAnswerSchema

logger = logging.getLogger(__name__)

VeritasAnswerFn = Callable[[ClarificationRequest], Awaitable[VeritasAnswerSchema]]

_RATIONALE_PREFIX_STRUCTURED = "structured_output_failed"
_RATIONALE_MARKER_QUESTION = "answer_was_question"

# DeferKind → (should_fallback_to_human, reason_template).
# ``low_confidence`` fallback is conditional on ``degrade_low_confidence``
# and handled separately in ``_should_fallback``.
_DEFER_TABLE: dict[DeferKind, tuple[bool, str]] = {
    "structured_output_failed": (
        True,
        "veritas structured output failed: {rationale}",
    ),
    "low_confidence": (
        False,  # conditional — upgraded by degrade_low_confidence
        "veritas low confidence ({conf:.2f} < {min:.2f})",
    ),
    "explicit": (
        False,
        "veritas explicit defer (confidence={conf:.2f})",
    ),
    "answer_was_question": (
        False,
        "veritas answer was a question",
    ),
}


class AutoClarificationPolicy:
    """Delegate clarifications to veritas; defer below confidence threshold.

    Adds two behaviors on top of the original policy:

    1. Every defer carries a :data:`DeferKind` so operators can distinguish
       legitimate "I don't know" defers from forced ones (LLM glitches).
    2. When `defer_kind == "structured_output_failed"` and an
       `interactive_fallback` policy is wired, the policy delegates to it
       (durable LangGraph `interrupt(...)`) instead of terminating the loop.
       The fallback is only present in interactive runs (`emit` wired);
       autopilot has no human at the other end and keeps the hard-defer path.

    When `degrade_low_confidence` is True and a human is attached, the same
    auto→manual upgrade applies to `low_confidence` defers — veritas wasn't
    confident, so surface the questions to the human instead of parking the
    loop silently. Ignored for autopilot (headless) runs.

    Origins listed in `force_manual_origins` skip veritas entirely and use
    the interactive relay (or defer when no human is attached).
    """

    def __init__(
        self,
        veritas_answer: VeritasAnswerFn,
        *,
        min_confidence: float = 0.4,
        interactive_fallback: ClarificationPolicy | None = None,
        force_manual_origins: Collection[ClarificationOrigin] | None = None,
        degrade_low_confidence: bool = False,
        tool_approval_pipeline: ToolApprovalPipeline | None = None,
    ) -> None:
        self._veritas_answer = veritas_answer
        self._min_confidence = min_confidence
        self._interactive_fallback = interactive_fallback
        self._force_manual_origins: frozenset[str] = frozenset(force_manual_origins or ())
        self._degrade_low_confidence = degrade_low_confidence
        self._tool_approval_pipeline = tool_approval_pipeline

    @property
    def min_confidence(self) -> float:
        return self._min_confidence

    @property
    def degrade_low_confidence(self) -> bool:
        return self._degrade_low_confidence

    @property
    def force_manual_origins(self) -> frozenset[str]:
        return self._force_manual_origins

    def requires_manual(self, origin_node: str) -> bool:
        """True when this origin must not be auto-answered by veritas."""
        return origin_node in self._force_manual_origins

    async def answer(self, request: ClarificationRequest) -> ClarificationAnswer:
        # --- tool-approval pipeline (deny-list-first) ---
        if request.origin_node == "tool_approval" and self._tool_approval_pipeline is not None:
            return await self._answer_tool_approval(request)

        # --- force-manual origins: skip veritas, go straight to human ---
        if self.requires_manual(request.origin_node):
            return await self._answer_force_manual(request)

        # --- veritas LLM auto-answer ---
        return await self._answer_veritas(request)

    async def _answer_tool_approval(self, request: ClarificationRequest) -> ClarificationAnswer:
        """Deny-list-first pipeline evaluation for tool_approval origins.

        In auto mode the pipeline auto-approves any action that passes deny +
        safety checks (absence of deny = implicit allow). In manual mode
        (force-manual origins), the pipeline still runs deny/safety (safety
        property) but defers non-matching actions to the human relay.
        """
        action_requests = request.metadata.get("action_requests", [])
        result = self._tool_approval_pipeline.evaluate(
            action_requests,
            workspace_root=request.loop_state.workspace_summary,
            auto_approve=not self.requires_manual(request.origin_node),
        )
        if result is not None:
            logger.info(
                "[clarification] tool_approval %s by stage=%s reason=%s",
                result.decision,
                result.stage,
                result.reason,
            )
            return ClarificationAnswer(
                answers=(result.decision,),
                source="static",
                confidence=1.0,
                audit={"stage": result.stage, "reason": result.reason},
            )
        # Pipeline returned None — manual mode with a human attached.
        # Route to the interactive relay so the human can decide.
        if self._interactive_fallback is not None:
            logger.info("[clarification] tool_approval no rule match; routing to interactive relay")
            return await self._delegate_to_fallback(request)
        raise ClarificationDeferredError(
            "tool_approval: no rule matched and veritas fallback disabled",
            request,
            kind="explicit",
        )

    async def _answer_force_manual(self, request: ClarificationRequest) -> ClarificationAnswer:
        """Force-manual origins skip veritas entirely.

        `await_clarification` already emitted with `mode=manual`, so we
        call `answer()` directly (no re-announce).
        """
        if self._interactive_fallback is not None:
            logger.info(
                "[clarification] origin=%s requires manual confirmation; skipping veritas",
                request.origin_node,
            )
            return await self._interactive_fallback.answer(request)
        raise ClarificationDeferredError(
            f"origin {request.origin_node} requires manual confirmation",
            request,
            kind="explicit",
        )

    async def _answer_veritas(self, request: ClarificationRequest) -> ClarificationAnswer:
        """Veritas LLM auto-answer with confidence-based defer/fallback."""
        result = await self._veritas_answer(request)
        kind = self._classify(result)

        if kind is not None and self._should_fallback(kind):
            if self._interactive_fallback is None:
                raise ClarificationDeferredError(
                    self._reason_for(kind, result),
                    request,
                    kind=kind,
                )
            if kind == "structured_output_failed":
                logger.warning(
                    "[veritas] structured output failed; falling back to interactive relay"
                )
            else:
                logger.info(
                    "[veritas] low confidence (%.2f); degrading to interactive relay",
                    result.confidence,
                )
            return await self._delegate_to_fallback(request)

        if kind is not None:
            raise ClarificationDeferredError(
                self._reason_for(kind, result),
                request,
                kind=kind,
            )

        answers = tuple(str(a).strip() for a in result.answers)
        if not answers or any(not a for a in answers):
            raise ClarificationDeferredError(
                "veritas returned empty answer(s)",
                request,
                kind="explicit",
            )

        return ClarificationAnswer(
            answers=answers,
            source="veritas",
            confidence=result.confidence,
            defer=False,
            audit={"rationale": result.rationale},
        )

    async def _delegate_to_fallback(self, request: ClarificationRequest) -> ClarificationAnswer:
        """Route to the interactive relay with auto→manual re-announce.

        Uses `answer_as_manual_fallback` when available so the TUI
        re-announces with `mode=manual` before pausing (the earlier
        `await_clarification` emit used `mode=auto`). Falls back to
        `answer()` for bare policies without the upgrade method.
        """
        fallback = self._interactive_fallback
        upgrade = getattr(fallback, "answer_as_manual_fallback", None)
        if callable(upgrade):
            return await upgrade(request)
        return await fallback.answer(request)

    def _classify(self, result: VeritasAnswerSchema) -> DeferKind | None:
        """Resolve a veritas result to a :data:`DeferKind`, or `None` to accept."""
        if result.defer:
            if result.rationale.startswith(_RATIONALE_PREFIX_STRUCTURED):
                return "structured_output_failed"
            if result.rationale == _RATIONALE_MARKER_QUESTION:
                return "answer_was_question"
            return "explicit"
        if result.confidence < self._min_confidence:
            return "low_confidence"
        return None

    def _should_fallback(self, kind: DeferKind) -> bool:
        """Whether this defer kind should route to the interactive fallback."""
        if kind not in _DEFER_TABLE:
            return False
        if kind == "low_confidence":
            return self._degrade_low_confidence
        return _DEFER_TABLE[kind][0]

    def _reason_for(self, kind: DeferKind, result: VeritasAnswerSchema) -> str:
        """Build the defer reason message for the given kind."""
        template = _DEFER_TABLE.get(kind, ("", "veritas deferred"))[1]
        return template.format(
            rationale=result.rationale,
            conf=result.confidence,
            min=self._min_confidence,
        )


__all__ = ["AutoClarificationPolicy", "VeritasAnswerFn"]
