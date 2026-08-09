"""Guard evaluation for LoopRail conditions (RFC-630 structured results)."""

from __future__ import annotations

import logging
import time
from collections import deque
from dataclasses import dataclass
from typing import Any, Protocol

from soothe.autopilot.rail.trace_store import GuardResult

logger = logging.getLogger(__name__)

# Rate-limit "WavePlan missing" warnings per job.
_WAVE_PLAN_MISSING_WARN_AT: dict[str, float] = {}
_WAVE_PLAN_MISSING_WARN_INTERVAL_S = 300.0


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


def _fanout_mode(structural: dict[str, Any]) -> bool:
    """True when the bound rail declared fanout (structure signal)."""
    return bool(structural.get("fanout_enabled")) or bool(structural.get("require_plan"))


def _structural_short_circuit(
    *,
    condition_name: str | None,
    event: str,
    trigger_tags: list[str],
    structural: dict[str, Any],
) -> GuardResult | None:
    """Resolve unambiguous LoopRail conditions from CE structural facts."""
    name = (condition_name or "").strip()
    if not name:
        return None
    structural = dict(structural or {})

    pending = int(structural.get("pending_or_active_count") or 0)
    architecture_done = bool(structural.get("all_architecture_terminal"))
    has_makers = bool(structural.get("implementation_goal_ids"))
    # Catalog expansion room: spawned_slices < effective_max_slices (IG-732).
    # Accept legacy structural key from older tests / dumps.
    below_slice_budget = bool(
        structural.get(
            "below_slice_budget",
            structural.get("wave_below_max", True),
        )
    )
    fanout_mode = _fanout_mode(structural)

    if name == "architecture_ready":
        # Initial fan-out only (no makers yet). Later growth uses
        # slices_ready_to_spawn (IG-732 streaming).
        require_plan = bool(structural.get("require_plan", False))
        wave_plan_ready = bool(structural.get("wave_plan_ready", False))
        plan_ok = (not require_plan) or wave_plan_ready
        if event == "dag_idle":
            ok = architecture_done and not has_makers and plan_ok
        else:
            ok = (
                event == "goal_completed"
                and "architecture" in trigger_tags
                and architecture_done
                and not has_makers
                and plan_ok
            )
        if not ok and architecture_done and not has_makers and require_plan and not wave_plan_ready:
            job_key = str(structural.get("job_id") or "")
            now = time.monotonic()
            last = _WAVE_PLAN_MISSING_WARN_AT.get(job_key, 0.0)
            if job_key and (now - last) >= _WAVE_PLAN_MISSING_WARN_INTERVAL_S:
                _WAVE_PLAN_MISSING_WARN_AT[job_key] = now
                logger.warning(
                    "WavePlan missing for job %s — architecture finished but "
                    "no flat WavePlan applied into rail state; makers will not "
                    "spawn until a valid plan is supplied via structured fields, "
                    "recommended dumps, wave_plan_path, or completion JSON "
                    "(restart daemon after upgrades so the architecture gate is live)",
                    job_key[:8],
                )
        return GuardResult(
            matched=ok,
            confidence=1.0,
            reasoning=(
                f"structural short-circuit: architecture_done={architecture_done} "
                f"has_makers={has_makers} require_plan={require_plan} "
                f"wave_plan_ready={wave_plan_ready} event={event}"
            ),
        )

    if name == "slices_ready_to_spawn":
        # Streaming catalog growth — do not require idle DAG.
        require_plan = bool(structural.get("require_plan", False))
        wave_plan_ready = bool(structural.get("wave_plan_ready", False))
        plan_ok = (not require_plan) or wave_plan_ready
        ready = bool(structural.get("slices_ready_unspawned"))
        ok = (
            event in {"goal_completed", "dag_idle"}
            and architecture_done
            and plan_ok
            and ready
            and below_slice_budget
        )
        return GuardResult(
            matched=ok,
            confidence=1.0,
            reasoning=(
                f"structural short-circuit: slices_ready_to_spawn ready={ready} "
                f"plan_ok={plan_ok} below_slice_budget={below_slice_budget} event={event}"
            ),
        )

    if name == "maker_needs_merge":
        unmerged = list(structural.get("unmerged_maker_ids") or [])
        resolve_done = bool(structural.get("trigger_is_merge_resolve"))
        maker_done = (
            event == "goal_completed"
            and "implementation" in trigger_tags
            and "feedback" not in trigger_tags
            and "resolve" not in trigger_tags
            and bool(structural.get("trigger_needs_merge"))
        )
        resolve_retry = event == "goal_completed" and resolve_done and bool(unmerged)
        idle_retry = (
            event == "dag_idle"
            and bool(unmerged)
            and not bool(structural.get("resolve_inflight_blocks_all"))
        )
        ok = maker_done or resolve_retry or idle_retry
        return GuardResult(
            matched=ok,
            confidence=1.0,
            reasoning=(
                f"structural short-circuit: maker_needs_merge "
                f"tags={trigger_tags} needs={structural.get('trigger_needs_merge')} "
                f"unmerged={len(unmerged)} resolve_done={resolve_done} "
                f"idle={event == 'dag_idle'}"
            ),
        )

    if name == "maker_merged":
        ok = (
            event == "goal_completed"
            and "implementation" in trigger_tags
            and bool(structural.get("trigger_just_merged"))
        )
        return GuardResult(
            matched=ok,
            confidence=1.0,
            reasoning="structural short-circuit: maker_merged",
        )

    if name == "wave_makers_done":
        # Integrate only when every *active* wave maker completed — pruned
        # retries and feedback optimize goals are excluded from the fact set.
        # dag_idle recovers when makers finished but integrate never spawned.
        all_makers_completed = bool(structural.get("all_implementation_completed"))
        no_integrate_yet = not bool(structural.get("integrate_goal_ids"))
        if event == "dag_idle":
            ok = all_makers_completed and has_makers and no_integrate_yet
        else:
            ok = (
                event == "goal_completed"
                and "implementation" in trigger_tags
                and all_makers_completed
                and has_makers
            )
        return GuardResult(
            matched=ok,
            confidence=1.0,
            reasoning=(
                f"structural short-circuit: all_makers_completed={all_makers_completed} "
                f"event={event} integrate_ids={bool(structural.get('integrate_goal_ids'))}"
            ),
        )

    if name == "needs_commit":
        # After integrate, or after makers when integrate was skipped.
        integrate_ids = list(structural.get("integrate_goal_ids") or [])
        commit_ids = list(structural.get("commit_goal_ids") or [])
        all_makers_completed = bool(structural.get("all_implementation_completed"))
        if event == "dag_idle":
            ok = (
                pending == 0
                and not commit_ids
                and (
                    bool(structural.get("any_integrate_completed"))
                    or (all_makers_completed and has_makers and not integrate_ids)
                )
            )
        elif event == "goal_completed" and "integrate" in trigger_tags:
            ok = True
        elif (
            event == "goal_completed"
            and "implementation" in trigger_tags
            and all_makers_completed
            and has_makers
            and not integrate_ids
            and not commit_ids
        ):
            ok = True
        else:
            ok = False
        return GuardResult(
            matched=ok,
            confidence=1.0,
            reasoning=f"structural short-circuit: needs_commit tags={trigger_tags} event={event}",
        )

    if name == "ready_for_next_wave":
        # Deprecated as a spawn barrier (RFC-231 §8). Alias to
        # slices_ready_to_spawn so legacy YAML does not withhold ready slices.
        require_plan = bool(structural.get("require_plan", False))
        wave_plan_ready = bool(structural.get("wave_plan_ready", False))
        plan_ok = (not require_plan) or wave_plan_ready
        ready = bool(structural.get("slices_ready_unspawned"))
        if not fanout_mode:
            return GuardResult(
                matched=False,
                confidence=1.0,
                reasoning=("structural short-circuit: ready_for_next_wave requires fan-out mode"),
            )
        ok = (
            event in {"goal_completed", "dag_idle"}
            and architecture_done
            and plan_ok
            and ready
            and below_slice_budget
        )
        return GuardResult(
            matched=ok,
            confidence=1.0,
            reasoning=(
                f"structural short-circuit: ready_for_next_wave→slices_ready "
                f"ready={ready} below_slice_budget={below_slice_budget} event={event}"
            ),
        )

    if name in {"ready_to_plan", "ready_to_fix", "scouts_done"}:
        exploration_done = bool(structural.get("all_exploration_terminal"))
        already_planned = bool(
            structural.get("implementation_goal_ids") or structural.get("planning_goal_ids")
        )
        if name == "scouts_done":
            ok = exploration_done
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

    if name in {"needs_review", "needs_check"}:
        commit_ids = list(structural.get("commit_goal_ids") or [])
        review_ids = list(structural.get("review_goal_ids") or [])
        if fanout_mode:
            # Commit gate: only review after commit completes.
            if event == "dag_idle":
                ok = (
                    pending == 0
                    and bool(commit_ids)
                    and bool(structural.get("all_commit_terminal", True))
                    and not review_ids
                )
            else:
                ok = event == "goal_completed" and "commit" in trigger_tags
        else:
            if event == "dag_idle":
                ok = False
            else:
                ok = event == "goal_completed" and (
                    "implementation" in trigger_tags or "commit" in trigger_tags
                )
                if commit_ids and not bool(structural.get("all_commit_terminal", True)):
                    ok = False
        return GuardResult(
            matched=ok,
            confidence=1.0,
            reasoning=f"structural short-circuit: review_trigger tags={trigger_tags} event={event}",
        )

    if name in {"needs_qa"}:
        qa_ids = list(structural.get("qa_goal_ids") or [])
        review_ids = list(structural.get("review_goal_ids") or [])
        if event == "dag_idle":
            ok = (
                pending == 0
                and bool(review_ids)
                and bool(structural.get("all_review_terminal", True))
                and not qa_ids
            )
        else:
            ok = event == "goal_completed" and "review" in trigger_tags
        return GuardResult(
            matched=ok,
            confidence=1.0,
            reasoning=f"structural short-circuit: needs_qa event={event} review_completed={ok}",
        )

    if name in {"branch_is_stuck"}:
        # Failed maker / implementation → rail replants (any rail).
        ok = event == "goal_failed" and (
            "maker" in trigger_tags or "implementation" in trigger_tags
        )
        return GuardResult(
            matched=ok,
            confidence=1.0,
            reasoning=(
                f"structural short-circuit: branch_is_stuck tags={trigger_tags} event={event}"
            ),
        )

    if name == "architecture_failed":
        # Failed planner/architecture → replant; not a maker retry.
        ok = event == "goal_failed" and "architecture" in trigger_tags
        return GuardResult(
            matched=ok,
            confidence=1.0,
            reasoning=(
                f"structural short-circuit: architecture_failed tags={trigger_tags} event={event}"
            ),
        )

    if name in {"needs_feedback"}:
        # Find→optimize→verify after wave QA / verify (fan-out only).
        feedback_inflight = bool(structural.get("feedback_inflight"))
        feedback_round = int(structural.get("feedback_round") or 0)
        max_feedback_rounds = int(structural.get("max_feedback_rounds") or 8)
        qa_or_verify_done = bool(structural.get("any_qa_completed")) or bool(
            structural.get("any_verify_completed")
        )
        if event == "dag_idle":
            trigger_ok = qa_or_verify_done
        elif event in {"goal_completed", "goal_failed"}:
            trigger_ok = "qa" in trigger_tags or "verify" in trigger_tags
        else:
            trigger_ok = False
        ok = (
            fanout_mode
            and trigger_ok
            and pending == 0
            and not feedback_inflight
            and feedback_round < max_feedback_rounds
            and not bool(structural.get("acceptance_met"))
        )
        return GuardResult(
            matched=ok,
            confidence=1.0,
            reasoning=(
                f"structural short-circuit: needs_feedback tags={trigger_tags} "
                f"event={event} fanout={fanout_mode} inflight={feedback_inflight} "
                f"round={feedback_round}/{max_feedback_rounds} "
                f"qa_or_verify_done={qa_or_verify_done}"
            ),
        )

    if name == "needs_human":
        # Tag-driven structural match; otherwise fall through to LLM.
        if "needs_human" in trigger_tags or "cutover" in trigger_tags:
            if event == "dag_idle":
                ok = pending == 0
            else:
                ok = event in {"goal_completed", "goal_failed"}
            return GuardResult(
                matched=ok,
                confidence=1.0,
                reasoning=(
                    f"structural short-circuit: needs_human tags={trigger_tags} event={event}"
                ),
            )
        return None

    if name == "checker_failed_recoverable":
        # Maker-checker: send_back from an independent review goal.
        if event == "goal_send_back" and "review" in trigger_tags:
            return GuardResult(
                matched=True,
                confidence=1.0,
                reasoning="structural short-circuit: checker_failed_recoverable send_back+review",
            )
        return None

    if name in {"job_complete"}:
        reviews = list(structural.get("review_goal_ids") or [])
        qas = list(structural.get("qa_goal_ids") or [])
        acceptance_met = bool(structural.get("acceptance_met", False))
        # Require at least one qa terminal when qa goals exist; else pending==0.
        ok = pending == 0 and (not qas or bool(structural.get("all_qa_terminal", True)))
        if reviews and pending == 0 and not qas:
            ok = True
        # Fan-out: host maturity / operator accept latch — do not complete on
        # idle DAG alone when acceptance is unmet. Slice budget no longer
        # blocks completion once acceptance is latched (IG-732; budget only
        # gates further spawn via slices_ready_to_spawn).
        if fanout_mode and not acceptance_met:
            ok = False
        return GuardResult(
            matched=ok,
            confidence=1.0,
            reasoning=(
                f"structural short-circuit: pending_or_active_count={pending} "
                f"qa_ids={qas} reviews={reviews} "
                f"below_slice_budget={below_slice_budget} "
                f"acceptance_met={acceptance_met} fanout={fanout_mode}"
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
        from pydantic import BaseModel, Field
        from soothe_nano.utils.llm.structured import (
            StructuredOutputError,
            invoke_structured_chat_typed,
        )

        from soothe.autopilot.prompts import build_guard_messages

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

        messages = build_guard_messages(
            event=ctx.event,
            goal_id=ctx.goal_id,
            trigger_tags=trigger_tags,
            condition_name=ctx.condition_name,
            structural=structural,
            sibling_statuses=ctx.sibling_statuses,
            tags_by_goal=ctx.tags_by_goal,
            retry_count=ctx.retry_count,
            condition_text=ctx.condition_text,
            goal_summary=ctx.goal_summary,
        )
        try:
            self.llm_calls += 1
            result = await invoke_structured_chat_typed(
                self.model,
                messages,
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
