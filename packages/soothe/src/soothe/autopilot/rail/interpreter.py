"""LoopRail interpreter: event → guard → CE builtin → append-only trace."""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from soothe.autopilot.rail.builtins_exec import (
    BuiltinResult,
    RailBuiltinExecutor,
    RailJobState,
)
from soothe.autopilot.rail.guards import GuardContext, GuardEvaluator
from soothe.autopilot.rail.trace_store import (
    GuardResult,
    MemoryRailTraceStore,
    RailTraceStore,
    RuleFireRecord,
)
from soothe.context.engine import ContextEngine, InvalidGoalTransitionError
from soothe.rails.catalog import LoopRailCatalog, RailDefinition

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
    ) -> None:
        self._ce = ce
        if builtins is not None:
            self._builtins = builtins
        else:
            self._builtins = RailBuiltinExecutor(ce, jobs_root=jobs_root)
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
        scout_count: int = 2,
        decompose_plan: list[dict[str, Any]] | None = None,
        workspace: str | None = None,
    ) -> RailDefinition:
        """Resolve rail and bind job state."""
        catalog = LoopRailCatalog(workspace=workspace) if workspace else self._catalog
        rail = catalog.resolve(rail_id)
        async with self._lock:
            self._rails[job_id] = rail
            self._rules[job_id] = _normalize_rules(rail)
        await self._builtins.bind_job(
            RailJobState(
                job_id=job_id,
                rail_id=rail.id,
                rail_version=rail.version,
                scout_count=scout_count,
                decompose_plan=decompose_plan,
            )
        )
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
        trigger_tags = tags_by_goal.get(event.goal_id or "", [])

        from soothe.context.models import TERMINAL_STATES

        exploration_ids = [gid for gid, tags in tags_by_goal.items() if "exploration" in tags]
        planning_ids = [gid for gid, tags in tags_by_goal.items() if "planning" in tags]
        architecture_ids = [gid for gid, tags in tags_by_goal.items() if "architecture" in tags]
        implementation_ids = [gid for gid, tags in tags_by_goal.items() if "implementation" in tags]
        integrate_ids = [gid for gid, tags in tags_by_goal.items() if "integrate" in tags]
        commit_ids = [gid for gid, tags in tags_by_goal.items() if "commit" in tags]
        review_ids = [gid for gid, tags in tags_by_goal.items() if "review" in tags]
        qa_ids = [gid for gid, tags in tags_by_goal.items() if "qa" in tags]
        feedback_ids = [gid for gid, tags in tags_by_goal.items() if "feedback" in tags]

        def _all_terminal(ids: list[str]) -> bool:
            return bool(ids) and all(siblings.get(gid) in TERMINAL_STATES for gid in ids)

        job_state = await self._builtins.job_state(event.job_id)
        wave_below_max = True
        feedback_round = 0
        max_feedback_rounds = 8
        acceptance_met = False
        if job_state is not None:
            wave_below_max = job_state.wave_index < job_state.max_waves
            feedback_round = int(job_state.feedback_round)
            max_feedback_rounds = int(job_state.max_feedback_rounds)
            acceptance_met = bool(job_state.acceptance_met)

        feedback_inflight = any(siblings.get(gid) in {"pending", "active"} for gid in feedback_ids)

        structural = {
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
            "all_integrate_terminal": _all_terminal(integrate_ids) if integrate_ids else True,
            "all_commit_terminal": _all_terminal(commit_ids) if commit_ids else True,
            "all_review_terminal": _all_terminal(review_ids) if review_ids else True,
            "all_qa_terminal": _all_terminal(qa_ids) if qa_ids else True,
            "feedback_inflight": feedback_inflight,
            "feedback_round": feedback_round,
            "max_feedback_rounds": max_feedback_rounds,
            "acceptance_met": acceptance_met,
            "wave_below_max": wave_below_max,
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
