"""Guard evaluation for LoopRail conditions (RFC-630 structured results)."""

from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Any, Protocol

from soothe.autopilot.rail.trace_store import GuardResult


@dataclass(frozen=True)
class GuardContext:
    """Inputs available to a guard evaluator for one event tick."""

    job_id: str
    event: str
    goal_id: str | None
    condition_name: str | None
    condition_text: str
    goal_summary: str
    sibling_statuses: dict[str, str]
    tags_by_goal: dict[str, list[str]]
    retry_count: int = 0
    extras: dict[str, Any] | None = None


class GuardEvaluator(Protocol):
    """Evaluate a rail ``when`` clause."""

    async def evaluate(self, ctx: GuardContext) -> GuardResult:
        """Return structured match result for ``ctx``."""


@dataclass
class ScriptedGuardEvaluator:
    """FIFO scripted responses keyed by ``(event, condition_name_or_text)``.

    Missing keys default to ``matched=False`` so tests must explicitly allow
    builtins to fire.
    """

    scripts: dict[tuple[str, str], deque[GuardResult]]

    @classmethod
    def from_mapping(
        cls,
        mapping: dict[tuple[str, str], list[dict[str, Any] | GuardResult | bool]],
    ) -> ScriptedGuardEvaluator:
        """Build from plain dicts / bools for ergonomic tests."""
        scripts: dict[tuple[str, str], deque[GuardResult]] = {}
        for key, values in mapping.items():
            queue: deque[GuardResult] = deque()
            for item in values:
                if isinstance(item, GuardResult):
                    queue.append(item)
                elif isinstance(item, bool):
                    queue.append(GuardResult(matched=item, reasoning="scripted bool"))
                else:
                    queue.append(
                        GuardResult(
                            matched=bool(item.get("matched", False)),
                            confidence=float(item.get("confidence", 1.0)),
                            reasoning=str(item.get("reasoning", "scripted")),
                        )
                    )
            scripts[key] = queue
        return cls(scripts=scripts)

    async def evaluate(self, ctx: GuardContext) -> GuardResult:
        key_name = (ctx.event, ctx.condition_name or "")
        key_text = (ctx.event, ctx.condition_text)
        for key in (key_name, key_text):
            queue = self.scripts.get(key)
            if queue is not None and queue:
                return queue.popleft()
            if queue is not None and not queue:
                # Exhausted explicit script → no match
                return GuardResult(
                    matched=False,
                    confidence=1.0,
                    reasoning="script exhausted",
                )
        return GuardResult(
            matched=False,
            confidence=1.0,
            reasoning="no script for condition",
        )


@dataclass
class AlwaysMatchGuardEvaluator:
    """Match every non-empty condition (and bare hooks with no when)."""

    reasoning: str = "always-match test guard"

    async def evaluate(self, ctx: GuardContext) -> GuardResult:
        return GuardResult(matched=True, confidence=1.0, reasoning=self.reasoning)


def _structural_short_circuit(
    *,
    condition_name: str | None,
    event: str,
    trigger_tags: list[str],
    structural: dict[str, Any],
) -> GuardResult | None:
    """Resolve unambiguous LoopRail conditions from CE structural facts."""
    name = (condition_name or "").strip()
    if not name or not structural:
        return None

    if name in {"ready_to_plan", "ready_to_fix", "scouts_done", "ready_for_next_wave"}:
        exploration_done = bool(structural.get("all_exploration_terminal"))
        already_planned = bool(
            structural.get("implementation_goal_ids") or structural.get("planning_goal_ids")
        )
        if name == "scouts_done":
            ok = exploration_done
        elif name == "ready_for_next_wave":
            # Allow repeated waves only when nothing is pending/active.
            ok = exploration_done and int(structural.get("pending_or_active_count") or 0) == 0
        else:
            # Gate once: do not re-fire after plan/implement already exists.
            ok = exploration_done and not already_planned
        return GuardResult(
            matched=ok,
            confidence=1.0,
            reasoning=(
                f"structural short-circuit: exploration_done={exploration_done} "
                f"already_planned={already_planned}"
            ),
        )

    if name in {"needs_review", "needs_check", "needs_security_review"}:
        ok = event == "goal_completed" and "implementation" in trigger_tags
        return GuardResult(
            matched=ok,
            confidence=1.0,
            reasoning=f"structural short-circuit: implementation_completed={ok}",
        )

    if name in {"needs_qa"}:
        ok = event == "goal_completed" and "review" in trigger_tags
        return GuardResult(
            matched=ok,
            confidence=1.0,
            reasoning=f"structural short-circuit: review_completed={ok}",
        )

    if name in {"job_complete"}:
        pending = int(structural.get("pending_or_active_count") or 0)
        reviews = list(structural.get("review_goal_ids") or [])
        qas = list(structural.get("qa_goal_ids") or [])
        # Require at least one qa terminal when qa goals exist; else pending==0.
        ok = pending == 0 and (not qas or bool(structural.get("all_qa_terminal", True)))
        if reviews and pending == 0 and not qas:
            ok = True
        return GuardResult(
            matched=ok,
            confidence=1.0,
            reasoning=(
                f"structural short-circuit: pending_or_active_count={pending} "
                f"qa_ids={qas} reviews={reviews}"
            ),
        )

    return None


@dataclass
class LLMGuardEvaluator:
    """Evaluate NL rail conditions with a structured chat-model call (RFC-630)."""

    model: Any
    min_confidence: float = 0.55
    role_hint: str = "fast"
    # When True, resolve clear structural cases without an LLM round-trip.
    structural_short_circuit: bool = True
    llm_calls: int = 0
    short_circuit_calls: int = 0

    async def evaluate(self, ctx: GuardContext) -> GuardResult:
        from langchain_core.messages import HumanMessage
        from pydantic import BaseModel, Field
        from soothe_nano.utils.llm.structured import (
            StructuredOutputError,
            invoke_structured_chat_typed,
        )

        class _GuardMatch(BaseModel):
            matched: bool = Field(description="Whether the condition holds now")
            confidence: float = Field(
                ge=0.0,
                le=1.0,
                description="Confidence in the match decision",
            )
            reasoning: str = Field(description="Brief evidence-based rationale")

        trigger_tags: list[str] = []
        structural: dict[str, Any] = {}
        if ctx.extras:
            trigger_tags = list(ctx.extras.get("trigger_tags") or [])
            structural = dict(ctx.extras.get("structural") or {})

        if self.structural_short_circuit:
            short = _structural_short_circuit(
                condition_name=ctx.condition_name,
                event=ctx.event,
                trigger_tags=trigger_tags,
                structural=structural,
            )
            if short is not None:
                self.short_circuit_calls += 1
                return short

        prompt = (
            "You evaluate a Soothe LoopRail guard condition for an autopilot job.\n"
            "Return whether the condition is TRUE right now given the event and DAG facts.\n"
            "Trust STRUCTURAL FACTS below as authoritative machine state.\n"
            "Guidance:\n"
            "- If the condition is about exploration/scouts being done or ready to plan, "
            "match=true when structural.all_exploration_terminal is true "
            "(treat completed scouts as sufficient unless a scout failed).\n"
            "- If the condition is about an implementation finishing / needing review, "
            "match=true when the trigger goal has tag 'implementation' "
            "and event is goal_completed.\n"
            "- If the condition is about needing QA after review, match=true when the "
            "trigger goal has tag 'review' and event is goal_completed.\n"
            "- If the condition is job_complete, match=true when "
            "structural.pending_or_active_count == 0 and any review/qa goals that exist "
            "are terminal.\n"
            "- Be conservative only when structural facts are missing or contradictory.\n\n"
            f"Event: {ctx.event}\n"
            f"Trigger goal_id: {ctx.goal_id}\n"
            f"Trigger goal summary: {ctx.goal_summary or '(none)'}\n"
            f"Trigger goal tags: {trigger_tags}\n"
            f"Condition name: {ctx.condition_name or '(inline)'}\n"
            f"Condition text:\n{ctx.condition_text}\n\n"
            f"STRUCTURAL FACTS: {structural}\n"
            f"Sibling/descendant statuses (goal_id -> status): {ctx.sibling_statuses}\n"
            f"Tags by goal: {ctx.tags_by_goal}\n"
            f"Trigger goal retry_count: {ctx.retry_count}\n"
        )
        try:
            self.llm_calls += 1
            result = await invoke_structured_chat_typed(
                self.model,
                [HumanMessage(content=prompt)],
                _GuardMatch,
            )
        except StructuredOutputError as exc:
            return GuardResult(
                matched=False,
                confidence=0.0,
                reasoning=f"structured guard failed: {type(exc).__name__}",
            )
        except Exception as exc:  # noqa: BLE001 — fail closed for rail policy
            return GuardResult(
                matched=False,
                confidence=0.0,
                reasoning=f"guard LLM error: {type(exc).__name__}",
            )

        matched = bool(result.matched) and float(result.confidence) >= self.min_confidence
        return GuardResult(
            matched=matched,
            confidence=float(result.confidence),
            reasoning=str(result.reasoning or ""),
        )


def empty_script() -> dict[tuple[str, str], deque[GuardResult]]:
    """Helper for mutable script maps."""
    return defaultdict(deque)
