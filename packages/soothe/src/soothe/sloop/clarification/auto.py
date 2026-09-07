"""Auto-mode clarification policy backed by the veritas subagent."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable, Collection
from typing import TYPE_CHECKING

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

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

VeritasAnswerFn = Callable[[ClarificationRequest], Awaitable[VeritasAnswerSchema]]

_RATIONALE_PREFIX_STRUCTURED = "structured_output_failed"
_RATIONALE_MARKER_QUESTION = "answer_was_question"

# DeferKind → reason_template.
_REASON_TEMPLATES: dict[DeferKind, str] = {
    "structured_output_failed": "veritas structured output failed: {rationale}",
    "low_confidence": "veritas low confidence ({conf:.2f} < {min:.2f})",
    "explicit": "veritas explicit defer (confidence={conf:.2f})",
    "answer_was_question": "veritas answer was a question",
}

# Sentinel answer for autopilot retry — tells the LLM to try a different action.
_RETRY_SENTINEL = "(retry)"


class AutoClarificationPolicy:
    """Delegate clarifications to veritas; fall back on any failure.

    TUI fallback: routes to the interactive relay (auto→manual upgrade).
    Autopilot fallback: returns a synthetic retry answer prompting the LLM
    to try a different action.
    """

    def __init__(
        self,
        veritas_answer: VeritasAnswerFn,
        *,
        min_confidence: float = 0.4,
        interactive_fallback: ClarificationPolicy | None = None,
        force_manual_origins: Collection[ClarificationOrigin] | None = None,
        degrade_to_manual_on_failure: bool = True,
        autopilot_retry_on_fail: bool = True,
        tool_approval_pipeline: ToolApprovalPipeline | None = None,
    ) -> None:
        self._veritas_answer = veritas_answer
        self._min_confidence = min_confidence
        self._interactive_fallback = interactive_fallback
        self._force_manual_origins: frozenset[str] = frozenset(force_manual_origins or ())
        self._degrade_to_manual_on_failure = degrade_to_manual_on_failure
        self._autopilot_retry_on_fail = autopilot_retry_on_fail
        self._tool_approval_pipeline = tool_approval_pipeline

    @property
    def min_confidence(self) -> float:
        return self._min_confidence

    @property
    def degrade_to_manual_on_failure(self) -> bool:
        return self._degrade_to_manual_on_failure

    @property
    def autopilot_retry_on_fail(self) -> bool:
        return self._autopilot_retry_on_fail

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

        ``escalate`` (banned safety rule) routes to the human relay when one
        is attached; under autopilot it degrades to an instructive reject.
        """
        # Resume replay: the answer is in flight; re-evaluating would
        # re-escalate before node_execute records the allowlist override.
        if request.metadata.get("resume_turn") and self._interactive_fallback is not None:
            return await self._delegate_to_fallback(request, announce=False)

        action_requests = request.metadata.get("action_requests", [])
        result = self._tool_approval_pipeline.evaluate(
            action_requests,
            workspace_root=request.loop_state.workspace_summary,
            auto_approve=not self.requires_manual(request.origin_node),
            allowlist=list(request.loop_state.tool_approval_allowlist),
        )
        if result is not None:
            logger.info(
                "[clarification] tool_approval %s by stage=%s reason=%s",
                result.decision,
                result.stage,
                result.reason,
            )
            # Banned safety action → escalate to a human when one is attached.
            if result.decision == "escalate":
                if self._interactive_fallback is not None:
                    logger.info(
                        "[clarification] tool_approval safety escalate rule=%s; "
                        "routing to human relay",
                        result.rule_id,
                    )
                    return await self._delegate_to_fallback(request, rule_id=result.rule_id)
                # Autopilot — degrade to an instructive reject.
                logger.info(
                    "[clarification] tool_approval safety escalate rule=%s; "
                    "autopilot degrade-to-instructive-reject",
                    result.rule_id,
                )
                return ClarificationAnswer(
                    answers=("reject",),
                    source="static",
                    confidence=1.0,
                    audit={
                        "stage": result.stage,
                        "reason": result.reason,
                        "rule_id": result.rule_id,
                        "instructive": True,
                    },
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
        # Autopilot — retry instead of hard defer.
        if self._autopilot_retry_on_fail:
            logger.info("[clarification] tool_approval no rule match; autopilot retry")
            return self._build_retry_answer(request)
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
        # No human — try autopilot retry, else hard defer.
        if self._autopilot_retry_on_fail:
            return self._build_retry_answer(request)
        raise ClarificationDeferredError(
            f"origin {request.origin_node} requires manual confirmation",
            request,
            kind="explicit",
        )

    async def _answer_veritas(self, request: ClarificationRequest) -> ClarificationAnswer:
        """Veritas LLM auto-answer with confidence-based fallback.

        On any veritas failure (DeferKind is not None):
        - TUI: route to the interactive relay when
          `degrade_to_manual_on_failure` is True.
        - Autopilot: return a synthetic retry answer when
          `autopilot_retry_on_fail` is True, prompting the LLM to try a
          different action.
        - Otherwise: hard defer (legacy behavior).
        """
        result = await self._veritas_answer(request)
        kind = self._classify(result)

        if kind is not None:
            reason = self._reason_for(kind, result)
            # Path 1: TUI — degrade to manual on any failure.
            if self._degrade_to_manual_on_failure and self._interactive_fallback is not None:
                if kind == "structured_output_failed":
                    logger.warning(
                        "[veritas] structured output failed; falling back to interactive relay"
                    )
                else:
                    logger.info(
                        "[veritas] %s; degrading to interactive relay",
                        kind,
                    )
                return await self._delegate_to_fallback(request)

            # Path 2: Autopilot — synthetic retry so the LLM tries again.
            if self._autopilot_retry_on_fail and self._interactive_fallback is None:
                logger.info(
                    "[veritas] %s; autopilot retry (letting LLM try a different action)",
                    kind,
                )
                return self._build_retry_answer(request)

            # Path 3: hard defer (legacy / opt-out).
            raise ClarificationDeferredError(reason, request, kind=kind)

        answers = tuple(str(a).strip() for a in result.answers)
        if not answers or any(not a for a in answers):
            # Empty answers — same fallback logic as above.
            reason = "veritas returned empty answer(s)"
            if self._degrade_to_manual_on_failure and self._interactive_fallback is not None:
                logger.info("[veritas] empty answers; degrading to interactive relay")
                return await self._delegate_to_fallback(request)
            if self._autopilot_retry_on_fail and self._interactive_fallback is None:
                logger.info("[veritas] empty answers; autopilot retry")
                return self._build_retry_answer(request)
            raise ClarificationDeferredError(reason, request, kind="explicit")

        return ClarificationAnswer(
            answers=answers,
            source="veritas",
            confidence=result.confidence,
            defer=False,
            audit={"rationale": result.rationale},
        )

    def _build_retry_answer(self, request: ClarificationRequest) -> ClarificationAnswer:
        """Build a synthetic retry answer for autopilot mode.

        The sentinel `"(retry)"` is fed back to the CoreAgent as the tool
        result for the ask_user / tool_approval interrupt, prompting the LLM
        to try a different action instead of parking the goal.
        """
        n_questions = len(request.questions) or 1
        return ClarificationAnswer(
            answers=tuple([_RETRY_SENTINEL] * n_questions),
            source="retry",
            confidence=0.0,
            audit={"reason": "veritas failed; autopilot retry"},
        )

    async def _delegate_to_fallback(
        self,
        request: ClarificationRequest,
        *,
        rule_id: str | None = None,
        announce: bool = True,
    ) -> ClarificationAnswer:
        """Route to the interactive relay with auto→manual re-announce.

        Prefers `answer_as_manual_fallback` (mode=manual emit) over bare
        `answer()`. `rule_id` stamps `audit["escalated_rule_id"]` so
        node_execute can record a rule-level allowlist override.
        `announce=False` for resume replays, where the card already exists.
        """
        fallback = self._interactive_fallback
        upgrade = getattr(fallback, "answer_as_manual_fallback", None)
        if callable(upgrade):
            answer = await upgrade(request, announce=announce)
        else:
            answer = await fallback.answer(request)
        if rule_id:
            audit = dict(answer.audit or {})
            audit.setdefault("escalated_rule_id", rule_id)
            return ClarificationAnswer(
                answers=answer.answers,
                source=answer.source,
                confidence=answer.confidence,
                defer=answer.defer,
                audit=audit,
            )
        return answer

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

    def _reason_for(self, kind: DeferKind, result: VeritasAnswerSchema) -> str:
        """Build the defer reason message for the given kind."""
        template = _REASON_TEMPLATES.get(kind, "veritas deferred")
        return template.format(
            rationale=result.rationale,
            conf=result.confidence,
            min=self._min_confidence,
        )


__all__ = ["AutoClarificationPolicy", "VeritasAnswerFn"]
