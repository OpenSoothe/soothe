"""LoopRail interpreter: event → guard → CE builtin → append-only trace."""

from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from soothe_autopilot.rails.builtins_exec import (
    BuiltinResult,
    RailBuiltinExecutor,
    RailJobState,
)

if TYPE_CHECKING:
    from soothe.config.models import SootheConfig
from soothe.context.engine import ContextEngine, InvalidGoalTransitionError

from soothe_autopilot.rails.catalog import LoopRailCatalog, RailDefinition
from soothe_autopilot.rails.guards import GuardContext, GuardEvaluator
from soothe_autopilot.rails.trace_store import (
    GuardResult,
    MemoryRailTraceStore,
    RailTraceStore,
    RuleFireRecord,
)

logger = logging.getLogger(__name__)

_CHECK_RETRY = re.compile(
    r"goal\.retry_count\s*>=\s*(\d+)",
    re.IGNORECASE,
)


@dataclass
class RailEvent:
    """Normalized rail event (YAML ``event:`` vocabulary)."""

    name: str
    job_id: str
    goal_id: str | None = None
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass
class _NormalizedRule:
    rule_id: str
    event: str
    when: Any  # None | str | dict
    then: str
    priority: int = 100
    allow_multiple: bool = False


class LoopRailInterpreter:
    """Job-scoped rail policy engine.

    StrangeLoop must not call this for DAG shape. Autopilot / harness emits
    ``RailEvent``s after CE mutations; the interpreter alone writes the trace.
    """

    def __init__(
        self,
        ce: ContextEngine,
        *,
        builtins: RailBuiltinExecutor | None = None,
        guards: GuardEvaluator | None = None,
        trace: RailTraceStore | None = None,
        catalog: LoopRailCatalog | None = None,
        jobs_root: Path | None = None,
        soothe_config: SootheConfig | None = None,
        rail_pause_auto_clarify: bool = True,
        on_user_intervention: Callable[[str], Awaitable[None]] | None = None,
    ) -> None:
        self._ce = ce
        if builtins is not None:
            self._builtins = builtins
        else:
            self._builtins = RailBuiltinExecutor(
                ce,
                jobs_root=jobs_root,
                soothe_config=soothe_config,
                rail_pause_auto_clarify=rail_pause_auto_clarify,
                on_user_intervention=on_user_intervention,
            )
        self._guards = guards
        self._trace = trace or MemoryRailTraceStore()
        self._catalog = catalog or LoopRailCatalog()
        self._rails: dict[str, RailDefinition] = {}
        self._rules: dict[str, list[_NormalizedRule]] = {}
        self._lock = asyncio.Lock()

    @property
    def builtins(self) -> RailBuiltinExecutor:
        return self._builtins

    @property
    def trace_store(self) -> RailTraceStore:
        return self._trace

    def set_guard_evaluator(self, guards: GuardEvaluator) -> None:
        """Replace the guard evaluator (tests inject scripts)."""
        self._guards = guards

    async def bind_job(
        self,
        job_id: str,
        *,
        rail_id: str,
        workspace: str | None = None,
        engine_max_parallel_goals: int | None = None,
    ) -> RailDefinition:
        """Resolve rail YAML, bind job state from optional ``fanout:``, fire-ready.

        Engine concerns (only):
          - ``engine_max_parallel_goals`` — spawn budget from
            ``autopilot.max_parallel_goals`` (capacity clamp).

        LoopRail concerns (from YAML / multi-form WavePlan transfer, never submit kwargs):
          - When ``fanout:`` is present: ``require_plan``, scout/max_waves.
            Absent ``fanout:`` → no wave-plan pollution.
          - WavePlan slices applied into ``RailJobState`` (SoT) from structured
            fields, recommended dumps, wave_plan_path, or completion findings.
          - flow ``then:`` builtins decide *when* to fan out

        Args:
            job_id: Root goal id.
            rail_id: LoopRail catalog id.
            workspace: Job workspace for catalog resolution.
            engine_max_parallel_goals: Autopilot pool schedule cap mirrored into
                rail spawn clamp.
        """
        catalog = LoopRailCatalog(workspace=workspace) if workspace else self._catalog
        rail = catalog.resolve(rail_id)
        async with self._lock:
            self._rails[job_id] = rail
            self._rules[job_id] = _normalize_rules(rail)

        fanout = dict(rail.fanout or {})
        wt_policy = dict(rail.worktrees or {})
        verb_overrides = dict(rail.verbs or {})
        budget = int(engine_max_parallel_goals) if engine_max_parallel_goals is not None else 32
        # Worktree lifecycle policy from rail YAML ``worktrees:`` (defaults True).
        wt_enabled = bool(wt_policy.get("enabled", True))
        wt_recycle_merge = bool(wt_policy.get("recycle_on_merge", True))
        wt_recycle_complete = bool(wt_policy.get("recycle_on_complete", True))
        # Fan-out / wave fields only when the rail declares ``fanout:``.
        if fanout:
            scout = int(fanout["scout_count"]) if "scout_count" in fanout else 2
            max_waves = int(fanout["max_waves"]) if "max_waves" in fanout else 3
            require_plan = bool(fanout.get("require_plan", False))
            state = RailJobState(
                job_id=job_id,
                rail_id=rail.id,
                rail_version=rail.version,
                scout_count=scout,
                fanout_enabled=True,
                require_plan=require_plan,
                max_waves=max_waves,
                engine_max_parallel_goals=budget,
                verb_overrides=verb_overrides,
                worktrees_enabled=wt_enabled,
                worktree_recycle_on_merge=wt_recycle_merge,
                worktree_recycle_on_complete=wt_recycle_complete,
            )
        else:
            state = RailJobState(
                job_id=job_id,
                rail_id=rail.id,
                rail_version=rail.version,
                fanout_enabled=False,
                engine_max_parallel_goals=budget,
                require_plan=False,
                verb_overrides=verb_overrides,
                worktrees_enabled=wt_enabled,
                worktree_recycle_on_merge=wt_recycle_merge,
                worktree_recycle_on_complete=wt_recycle_complete,
            )
        await self._builtins.bind_job(state)
        if fanout:
            await self._builtins.ingest_wave_plan(job_id)
        return rail

    async def handle(self, event: RailEvent) -> list[RuleFireRecord]:
        """Evaluate matching rules for one event; return newly appended records."""
        job_id = event.job_id
        async with self._lock:
            rail = self._rails.get(job_id)
            rules = list(self._rules.get(job_id, ()))
        if rail is None:
            logger.debug("No rail bound for job %s; ignoring %s", job_id, event.name)
            return []

        rules = [r for r in rules if r.event == event.name]
        rules = sorted(rules, key=lambda r: r.priority)

        fired: list[RuleFireRecord] = []
        for rule in rules:
            matched, guard_result, condition_label = await self._eval_when(rail, rule, event)
            record = RuleFireRecord(
                timestamp=datetime.now(UTC),
                rule_id=rule.rule_id,
                event=event.name,
                condition=condition_label,
                guard_result=guard_result,
                builtin=rule.then if matched else None,
                builtin_result=None,
                goal_id=event.goal_id,
            )
            if matched:
                try:
                    result = await self._builtins.invoke(
                        rule.then,
                        job_id=job_id,
                        trigger_goal_id=event.goal_id,
                    )
                except InvalidGoalTransitionError as exc:
                    # Builtin attempted an invalid state transition (e.g. completing
                    # an already-terminal goal).  Treat as a benign skip, not an
                    # error — the guard still matched and the rule fired.
                    logger.debug(
                        "Builtin %s skipped: %s (goal already in target state)",
                        rule.then,
                        exc,
                    )
                    result = BuiltinResult(
                        status="skipped",
                        detail=f"invalid transition: {type(exc).__name__}",
                    )
                record.builtin_result = result.status
                if result.status not in ("success", "skipped"):
                    record.guard_result = GuardResult(
                        matched=True,
                        confidence=guard_result.confidence,
                        reasoning=f"{guard_result.reasoning}; builtin={result.detail}",
                    )
            self._trace.append(job_id, record)
            fired.append(record)
            if matched:
                logger.info(
                    "Rail rule fired job_id=%s event=%s rule_id=%s builtin=%s result=%s goal_id=%s",
                    job_id,
                    event.name,
                    rule.rule_id,
                    rule.then,
                    getattr(record, "builtin_result", None) or "-",
                    event.goal_id or "-",
                )
            else:
                logger.debug(
                    "Rail rule unmatched job_id=%s event=%s rule_id=%s",
                    job_id,
                    event.name,
                    rule.rule_id,
                )
            if matched and not rule.allow_multiple:
                break
            if matched and rule.allow_multiple:
                continue
            # unmatched: keep walking (trace still records no-fire attempts only
            # when we want audit — draft says guard results always appended when
            # evaluated). Continue to next rule.
        return fired

    async def _eval_when(
        self,
        rail: RailDefinition,
        rule: _NormalizedRule,
        event: RailEvent,
    ) -> tuple[bool, GuardResult, str | None]:
        when = rule.when
        if when is None or when == "":
            return True, GuardResult(matched=True, reasoning="no when clause"), None

        # Deterministic check shortcuts
        if isinstance(when, dict) and "check" in when:
            ok = _eval_check(when["check"], event, self._ce)
            return (
                ok,
                GuardResult(matched=ok, reasoning=f"check: {when['check']}"),
                str(when["check"]),
            )

        if isinstance(when, dict) and "nl" in when:
            when = when["nl"]

        if isinstance(when, dict) and "all" in when:
            # Evaluate each; all must match
            parts = when["all"]
            labels: list[str] = []
            for part in parts:
                sub = _NormalizedRule(
                    rule_id=rule.rule_id,
                    event=rule.event,
                    when=part
                    if not isinstance(part, dict) or "nl" in part or "check" in part
                    else part,
                    then=rule.then,
                )
                if isinstance(part, dict) and "nl" in part:
                    sub = _NormalizedRule(
                        rule_id=rule.rule_id,
                        event=rule.event,
                        when=part["nl"],
                        then=rule.then,
                    )
                matched, gr, label = await self._eval_when(rail, sub, event)
                labels.append(label or "")
                if not matched:
                    return False, gr, "&".join(labels)
            return True, GuardResult(matched=True, reasoning="all matched"), "&".join(labels)

        condition_name: str | None = None
        condition_text: str
        if isinstance(when, str) and when in rail.conditions:
            condition_name = when
            condition_text = rail.conditions[when]
        elif isinstance(when, str) and when.startswith("$conditions."):
            condition_name = when.removeprefix("$conditions.")
            condition_text = rail.conditions.get(condition_name, when)
        elif isinstance(when, str):
            # Bare NL or condition name used inline
            if when in rail.conditions:
                condition_name = when
                condition_text = rail.conditions[when]
            else:
                condition_text = when
        else:
            condition_text = str(when)

        if self._guards is None:
            # Fail closed without evaluator
            return (
                False,
                GuardResult(matched=False, reasoning="no guard evaluator configured"),
                condition_name or condition_text,
            )

        goal = await self._ce.get_goal(event.goal_id) if event.goal_id else None
        descendants = await self._builtins.descendant_goals(event.job_id)
        siblings = {g.id: g.status for g in descendants}
        tags_by_goal = await self._builtins.tags_by_goal(event.job_id)
        trigger_tags = list(tags_by_goal.get(event.goal_id or "", []))
        # IG-692: fail-closed — repair empty trigger tags from CE before guards.
        if event.goal_id and not trigger_tags:
            repaired = await self._builtins.ensure_trigger_tags(event.job_id, event.goal_id)
            if repaired:
                trigger_tags = list(repaired)
                tags_by_goal = await self._builtins.tags_by_goal(event.job_id)
                logger.info(
                    "Rail repaired empty trigger tags for goal %s from CE: %s",
                    event.goal_id,
                    trigger_tags,
                )
            else:
                logger.warning(
                    "Rail trigger tags empty for goal %s after CE hydrate (job=%s)",
                    event.goal_id,
                    event.job_id,
                )

        from soothe.context.models import TERMINAL_STATES

        from soothe_autopilot.verify.job_maturity import latch_acceptance_met

        job_state = await self._builtins.job_state(event.job_id)
        below_slice_budget = True
        feedback_round = 0
        max_feedback_rounds = 8
        rail_acceptance = False
        slices_ready_unspawned = False
        trigger_needs_merge = False
        trigger_just_merged = False
        trigger_is_merge_resolve = False
        unmerged_maker_ids: list[str] = []
        resolve_inflight_blocks_all = False
        if job_state is not None:
            # Slice expansion budget (not a wave gate — IG-732).
            below_slice_budget = len(job_state.spawned_slices) < job_state.effective_max_slices()
            feedback_round = int(job_state.feedback_round)
            max_feedback_rounds = int(job_state.max_feedback_rounds)
            rail_acceptance = bool(job_state.acceptance_met)
            slices_ready_unspawned = self._builtins.has_ready_unspawned_slices(event.job_id)
            unmerged_maker_ids = self._builtins.unmerged_maker_ids(event.job_id)
            if unmerged_maker_ids:
                resolve_inflight_blocks_all = all(
                    self._builtins.resolve_inflight_for_maker(event.job_id, mid) is not None
                    for mid in unmerged_maker_ids
                )
            if event.goal_id:
                tann = job_state.annotations.get(event.goal_id)
                if tann is not None and "implementation" in (tann.tags or []):
                    trigger_needs_merge = tann.branch_status in {
                        "active",
                        "conflict",
                    }
                    trigger_just_merged = tann.branch_status == "merged"
                    ttags = set(tann.tags or [])
                    trigger_is_merge_resolve = "resolve" in ttags and "merge" in ttags
        root = await self._ce.get_goal(event.job_id)
        acceptance_met = latch_acceptance_met(
            rail_acceptance_met=rail_acceptance,
            maturity=root.maturity if root is not None else None,
        )

        def _branch_status(gid: str) -> str | None:
            if job_state is not None:
                ann = job_state.annotations.get(gid)
                if ann is not None and ann.branch_status:
                    return ann.branch_status
            node = next((g for g in descendants if g.id == gid), None)
            if node is None:
                node = self._ce._dag.get_goal(gid)
            return getattr(node, "branch_status", None) if node is not None else None

        def _is_wave_maker(gid: str, tags: list[str]) -> bool:
            """Active wave maker — exclude feedback optimize and pruned retries."""
            if "implementation" not in tags:
                return False
            if "feedback" in tags:
                return False
            return _branch_status(gid) != "pruned"

        exploration_ids = [gid for gid, tags in tags_by_goal.items() if "exploration" in tags]
        planning_ids = [gid for gid, tags in tags_by_goal.items() if "planning" in tags]
        architecture_ids = [gid for gid, tags in tags_by_goal.items() if "architecture" in tags]
        implementation_ids = [
            gid for gid, tags in tags_by_goal.items() if _is_wave_maker(gid, tags)
        ]
        integrate_ids = [gid for gid, tags in tags_by_goal.items() if "integrate" in tags]
        commit_ids = [gid for gid, tags in tags_by_goal.items() if "commit" in tags]
        review_ids = [gid for gid, tags in tags_by_goal.items() if "review" in tags]
        qa_ids = [gid for gid, tags in tags_by_goal.items() if "qa" in tags]
        feedback_ids = [gid for gid, tags in tags_by_goal.items() if "feedback" in tags]
        verify_ids = [gid for gid, tags in tags_by_goal.items() if "verify" in tags]

        def _all_terminal(ids: list[str]) -> bool:
            return bool(ids) and all(siblings.get(gid) in TERMINAL_STATES for gid in ids)

        def _all_completed(ids: list[str]) -> bool:
            return bool(ids) and all(siblings.get(gid) == "completed" for gid in ids)

        def _any_completed(ids: list[str]) -> bool:
            return any(siblings.get(gid) == "completed" for gid in ids)

        feedback_inflight = any(siblings.get(gid) in {"pending", "active"} for gid in feedback_ids)

        require_plan = False
        fanout_enabled = False
        wave_plan_ready = True
        if job_state is not None:
            require_plan = bool(job_state.require_plan)
            fanout_enabled = bool(job_state.fanout_enabled) or require_plan
            if require_plan:
                wave_plan_ready = self._builtins.is_wave_plan_ready(event.job_id)

        structural = {
            "job_id": event.job_id,
            "exploration_goal_ids": exploration_ids,
            "planning_goal_ids": planning_ids,
            "architecture_goal_ids": architecture_ids,
            "implementation_goal_ids": implementation_ids,
            "integrate_goal_ids": integrate_ids,
            "commit_goal_ids": commit_ids,
            "review_goal_ids": review_ids,
            "qa_goal_ids": qa_ids,
            "feedback_goal_ids": feedback_ids,
            "all_exploration_terminal": _all_terminal(exploration_ids),
            "all_architecture_terminal": _all_terminal(architecture_ids),
            "all_implementation_terminal": _all_terminal(implementation_ids),
            "all_implementation_completed": _all_completed(implementation_ids),
            "all_integrate_terminal": _all_terminal(integrate_ids) if integrate_ids else True,
            "all_commit_terminal": _all_terminal(commit_ids) if commit_ids else True,
            "all_review_terminal": _all_terminal(review_ids) if review_ids else True,
            "all_qa_terminal": _all_terminal(qa_ids) if qa_ids else True,
            "any_qa_completed": _any_completed(qa_ids),
            "any_verify_completed": _any_completed(verify_ids),
            "any_integrate_completed": _any_completed(integrate_ids),
            "feedback_inflight": feedback_inflight,
            "feedback_round": feedback_round,
            "max_feedback_rounds": max_feedback_rounds,
            "acceptance_met": acceptance_met,
            "below_slice_budget": below_slice_budget,
            "slices_ready_unspawned": slices_ready_unspawned,
            "trigger_needs_merge": trigger_needs_merge,
            "trigger_just_merged": trigger_just_merged,
            "trigger_is_merge_resolve": trigger_is_merge_resolve,
            "unmerged_maker_ids": unmerged_maker_ids,
            "resolve_inflight_blocks_all": resolve_inflight_blocks_all,
            "fanout_enabled": fanout_enabled,
            "require_plan": require_plan,
            "wave_plan_ready": wave_plan_ready,
            "retry_count": int(goal.retry_count) if goal else 0,
            "pending_or_active_count": sum(
                1
                for gid, st in siblings.items()
                if gid != event.job_id and st in {"pending", "active"}
            ),
            "trigger_findings": list(goal.findings) if goal else [],
        }
        ctx = GuardContext(
            job_id=event.job_id,
            event=event.name,
            goal_id=event.goal_id,
            condition_name=condition_name,
            condition_text=condition_text,
            goal_summary=(goal.description if goal else "")[:500],
            sibling_statuses=siblings,
            tags_by_goal=tags_by_goal,
            retry_count=int(goal.retry_count) if goal else 0,
            extras={"trigger_tags": trigger_tags, "structural": structural},
        )
        result = await self._guards.evaluate(ctx)
        return result.matched, result, condition_name or condition_text


def _rule_event(entry: dict[str, Any]) -> str:
    """Read flow/rule trigger name (canonical ``event``, legacy ``on``)."""
    if "event" in entry:
        return str(entry["event"])
    if "on" in entry:
        return str(entry["on"])
    if True in entry:  # YAML 1.1 bare ``on:`` → boolean key
        return str(entry[True])
    return ""


def _normalize_rules(rail: RailDefinition) -> list[_NormalizedRule]:
    """Merge flow + rules; explicit rules precede flow at equal priority."""
    out: list[_NormalizedRule] = []
    for i, entry in enumerate(rail.flow):
        then = entry.get("then")
        if not isinstance(then, str):
            continue
        out.append(
            _NormalizedRule(
                rule_id=f"flow[{i}]",
                event=_rule_event(entry),
                when=entry.get("when"),
                then=then,
                priority=int(entry.get("priority", 100)),
                allow_multiple=bool(entry.get("allow_multiple", False)),
            )
        )
    for i, entry in enumerate(rail.rules):
        then = entry.get("then")
        if not isinstance(then, str):
            continue
        out.append(
            _NormalizedRule(
                rule_id=str(entry.get("id") or f"rule[{i}]"),
                event=_rule_event(entry),
                when=entry.get("when"),
                then=then,
                priority=int(entry.get("priority", 99)),  # prefer explicit slightly
                allow_multiple=bool(entry.get("allow_multiple", False)),
            )
        )
    return out


def _eval_check(expr: str, event: RailEvent, ce: ContextEngine) -> bool:
    """Tiny deterministic predicate evaluator for tests / opt-in checks."""
    m = _CHECK_RETRY.search(str(expr))
    if m and event.goal_id:
        goal = ce.get_goal_sync(event.goal_id)
        if goal is None:
            return False
        return goal.retry_count >= int(m.group(1))
    return False
