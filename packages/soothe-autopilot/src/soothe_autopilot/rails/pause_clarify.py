"""Veritas auto-clarification for LoopRail `pause_for_user`.

Host-side only: synthesizes a PROCEED/PAUSE gate question, runs the same
auto clarification policy autopilot workers use, and maps the answer to a
rail decision without entering StrangeLoop `await_clarification`.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal

from soothe.sloop.clarification.origins import ORIGIN_RAIL_PAUSE
from soothe.sloop.clarification.protocol import (
    ClarificationDeferredError,
    ClarificationRequest,
    LoopStateView,
)
from soothe.sloop.clarification.runtime_factory import build_clarification_policy_for_runner

if TYPE_CHECKING:
    from soothe.config.models import SootheConfig
    from soothe.context.models import GoalNode

logger = logging.getLogger(__name__)

PauseClarifyOutcome = Literal["proceed", "deny", "defer"]

_PROCEED_TOKENS = frozenset({"proceed", "yes", "continue", "approve"})
_PAUSE_TOKENS = frozenset({"pause", "no", "deny", "suspend", "reject"})
_TOKEN_SPLIT = re.compile(r"[\s,:;]+")


@dataclass(frozen=True)
class PauseClarifyDecision:
    """Result of Veritas (or fail-open) for a rail human gate."""

    outcome: PauseClarifyOutcome
    confidence: float | None = None
    rationale: str = ""
    answers: tuple[str, ...] = ()
    source: str = "veritas"


def parse_gate_answer_token(answers: tuple[str, ...]) -> PauseClarifyOutcome:
    """Map Veritas answer text to proceed/deny/defer via fixed vocabulary.

    Only the first whitespace-delimited token of the first answer is considered
    (structured gate vocabulary — not content judgment on job text).
    """
    if not answers:
        return "defer"
    raw = str(answers[0] or "").strip().lower()
    if not raw:
        return "defer"
    token = _TOKEN_SPLIT.split(raw, maxsplit=1)[0].strip(" .\"'`")
    if token in _PROCEED_TOKENS:
        return "proceed"
    if token in _PAUSE_TOKENS:
        return "deny"
    return "defer"


def build_pause_gate_question(*, irreversible_hint: bool) -> str:
    """Fixed yes/no gate question for Veritas."""
    risk = (
        "The rail matched an irreversible / cutover-style human gate. "
        if irreversible_hint
        else "The rail matched a human pause gate (pause_for_user). "
    )
    return (
        f"{risk}"
        "Should autopilot CONTINUE without suspending for an operator "
        "(answer exactly PROCEED), or PAUSE the job for a human "
        "(answer exactly PAUSE)?"
    )


def build_pause_loop_state(
    *,
    job: GoalNode,
    trigger: GoalNode | None,
    trigger_tags: list[str] | None,
) -> LoopStateView:
    """Build a narrow LoopStateView for the rail pause gate."""
    tags = list(trigger_tags or [])
    if trigger is not None and not tags:
        tags = list(trigger.rail_tags or [])
    tag_line = f"trigger_tags={tags}" if tags else "trigger_tags=[]"
    trigger_desc = (trigger.description if trigger is not None else "") or ""
    plan = f"{tag_line}; trigger={(trigger.id[:8] if trigger else 'none')}"
    recent: list[str] = []
    if trigger_desc.strip():
        recent.append(trigger_desc.strip()[:1200])
    findings = getattr(trigger, "findings", None) if trigger is not None else None
    if isinstance(findings, str) and findings.strip():
        recent.append(findings.strip()[:800])
    elif isinstance(findings, list):
        for item in findings[:3]:
            recent.append(str(item)[:400])
    return LoopStateView(
        goal_id=job.id,
        goal_description=(job.description or "")[:2000],
        user_request=(job.description or "")[:2000],
        iteration=0,
        intent_classification="rail_pause",
        plan_summary=plan[:500],
        recent_step_outputs=tuple(recent),
        workspace_summary=(job.workspace or None),
        active_skills=(),
        active_mcp_servers=(),
    )


async def run_rail_pause_clarify(
    *,
    soothe_config: SootheConfig,
    job: GoalNode,
    trigger: GoalNode | None,
    trigger_tags: list[str] | None = None,
) -> PauseClarifyDecision:
    """Run Veritas auto-clarification for `pause_for_user`.

    Returns:
        Decision with outcome `proceed`, `deny`, or `defer`. Policy
        deferrals and unexpected errors map to `defer` (caller suspends).
    """
    tags = list(trigger_tags or [])
    if trigger is not None and not tags:
        tags = list(trigger.rail_tags or [])
    irreversible = "needs_human" in tags or "cutover" in tags
    question = build_pause_gate_question(irreversible_hint=irreversible)
    view = build_pause_loop_state(job=job, trigger=trigger, trigger_tags=tags)
    request = ClarificationRequest(
        questions=(question,),
        origin_node=ORIGIN_RAIL_PAUSE,
        origin_interrupt_id=f"rail-pause:{job.id}",
        loop_state=view,
    )
    policy = build_clarification_policy_for_runner(
        soothe_config,
        mode="auto",
        human_attached=False,
        thread_id=f"rail_pause:{job.id}",
        loop_id=f"rail_pause:{job.id}",
    )
    try:
        answer = await policy.answer(request)
    except ClarificationDeferredError as exc:
        logger.info(
            "Rail pause Veritas deferred job=%s kind=%s reason=%s",
            job.id[:8],
            exc.kind,
            exc.reason[:160],
        )
        return PauseClarifyDecision(
            outcome="defer",
            rationale=exc.reason[:500],
            source="veritas_defer",
        )
    except Exception as exc:
        logger.warning(
            "Rail pause Veritas failed job=%s; failing open to suspend",
            job.id[:8],
            exc_info=True,
        )
        return PauseClarifyDecision(
            outcome="defer",
            rationale=f"veritas_error:{type(exc).__name__}:{exc}"[:500],
            source="error",
        )

    if answer.defer:
        return PauseClarifyDecision(
            outcome="defer",
            confidence=answer.confidence,
            rationale=str((answer.audit or {}).get("rationale") or "deferred")[:500],
            answers=tuple(answer.answers),
            source=answer.source,
        )

    outcome = parse_gate_answer_token(tuple(answer.answers))
    rationale = str((answer.audit or {}).get("rationale") or "")[:500]
    return PauseClarifyDecision(
        outcome=outcome,
        confidence=answer.confidence,
        rationale=rationale,
        answers=tuple(answer.answers),
        source=answer.source,
    )


def decision_to_audit(decision: PauseClarifyDecision) -> dict[str, Any]:
    """JSON-serializable audit blob for `rail_state.json`."""
    return {
        "outcome": decision.outcome,
        "confidence": decision.confidence,
        "rationale": decision.rationale,
        "answers": list(decision.answers),
        "source": decision.source,
    }


__all__ = [
    "PauseClarifyDecision",
    "PauseClarifyOutcome",
    "decision_to_audit",
    "parse_gate_answer_token",
    "run_rail_pause_clarify",
]
