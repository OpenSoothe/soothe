"""Pseudo-autopilot harness for LoopRail multi-turn tests (scripted or LLM guards)."""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from soothe.autopilot.rail import (
    LoopRailInterpreter,
    MemoryRailTraceStore,
    RailEvent,
    ScriptedGuardEvaluator,
    export_trace_evaluation,
)
from soothe.autopilot.rail.guards import GuardResult
from soothe.context.engine import ContextEngine
from soothe.context.models import GoalNode

OnReady = Callable[[GoalNode, int], Awaitable[None]]


@dataclass
class RailHarness:
    """Drive real CE + rail interpreter with pseudo goal execution."""

    ce: ContextEngine = field(default_factory=ContextEngine)
    trace: MemoryRailTraceStore = field(default_factory=MemoryRailTraceStore)
    interpreter: LoopRailInterpreter | None = None
    job_id: str | None = None
    turn: int = 0

    def __post_init__(self) -> None:
        if self.interpreter is None:
            self.interpreter = LoopRailInterpreter(self.ce, trace=self.trace)

    async def submit(
        self,
        description: str,
        *,
        rail_id: str,
        scout_count: int = 2,
        decompose_plan: list[dict[str, Any]] | None = None,
        guard_scripts: dict[tuple[str, str], list[Any]] | None = None,
        guard_evaluator: Any | None = None,
    ) -> str:
        """Create job root, bind rail, emit ``job_start``."""
        assert self.interpreter is not None
        root = await self.ce.create_goal(description, priority=90, source="user")
        root.status = "active"
        self.job_id = root.id
        await self.interpreter.bind_job(
            root.id,
            rail_id=rail_id,
            scout_count=scout_count,
            decompose_plan=decompose_plan,
        )
        if guard_evaluator is not None:
            self.interpreter.set_guard_evaluator(guard_evaluator)
        elif guard_scripts is not None:
            self.interpreter.set_guard_evaluator(ScriptedGuardEvaluator.from_mapping(guard_scripts))
        await self.interpreter.handle(RailEvent(name="job_start", job_id=root.id))
        return root.id

    def ready_goals(self, *, limit: int = 50) -> list[GoalNode]:
        assert self.job_id is not None
        ready = self.ce.peek_ready_goals(limit=limit)
        return [g for g in ready if g.id != self.job_id and g.parent_id == self.job_id]

    async def activate(self, goal_id: str) -> None:
        await self.ce.activate_goal(goal_id, loop_id=f"pseudo__{goal_id}")

    async def pseudo_complete(self, goal_id: str) -> list[Any]:
        assert self.interpreter is not None and self.job_id is not None
        goal = await self.ce.get_goal(goal_id)
        if goal is None:
            raise KeyError(goal_id)
        if goal.status == "pending":
            await self.activate(goal_id)
        # Give LLM guards something concrete for "findings sufficient" wording.
        if not goal.findings:
            goal.findings = [f"Pseudo-complete: {goal.description[:120]}"]
        await self.ce.complete_goal(goal_id)
        return await self.interpreter.handle(
            RailEvent(name="goal_completed", job_id=self.job_id, goal_id=goal_id)
        )

    async def pseudo_fail(self, goal_id: str, error: str = "pseudo fail") -> list[Any]:
        assert self.interpreter is not None and self.job_id is not None
        goal = await self.ce.get_goal(goal_id)
        if goal is None:
            raise KeyError(goal_id)
        if goal.status == "pending":
            await self.activate(goal_id)
        await self.ce.fail_goal(goal_id, error)
        goal.retry_count += 1
        return await self.interpreter.handle(
            RailEvent(
                name="goal_failed",
                job_id=self.job_id,
                goal_id=goal_id,
                payload={"error": error},
            )
        )

    async def pseudo_send_back(self, goal_id: str) -> list[Any]:
        assert self.interpreter is not None and self.job_id is not None
        goal = await self.ce.get_goal(goal_id)
        if goal is not None:
            goal.send_back_count += 1
        return await self.interpreter.handle(
            RailEvent(name="goal_send_back", job_id=self.job_id, goal_id=goal_id)
        )

    async def user_intervention(self) -> list[Any]:
        assert self.interpreter is not None and self.job_id is not None
        return await self.interpreter.handle(
            RailEvent(name="user_intervention", job_id=self.job_id)
        )

    async def tick_dag_idle(self) -> list[Any]:
        assert self.interpreter is not None and self.job_id is not None
        return await self.interpreter.handle(RailEvent(name="dag_idle", job_id=self.job_id))

    def job_completed(self) -> bool:
        assert self.job_id is not None and self.interpreter is not None
        state = self.interpreter.builtins.job_state(self.job_id)
        return bool(state and state.completed)

    def job_suspended(self) -> bool:
        assert self.job_id is not None and self.interpreter is not None
        state = self.interpreter.builtins.job_state(self.job_id)
        return bool(state and state.suspended)

    def tags(self, goal_id: str) -> list[str]:
        assert self.job_id is not None and self.interpreter is not None
        return list(self.interpreter.builtins.annotation(goal_id, self.job_id).tags)

    def successful_builtins(self) -> list[str]:
        assert self.job_id is not None
        return [
            r.builtin
            for r in self.trace.read(self.job_id)
            if r.builtin and r.guard_result.matched and r.builtin_result == "success"
        ]

    def evaluation(self, *, expected_builtins: list[str] | None = None) -> dict[str, Any]:
        assert self.job_id is not None
        return export_trace_evaluation(
            self.job_id,
            self.trace,
            expected_builtins=expected_builtins,
        )

    async def run_turns(
        self,
        on_ready: OnReady,
        *,
        max_turns: int = 30,
    ) -> dict[str, Any]:
        assert self.job_id is not None
        for self.turn in range(max_turns):
            if self.job_completed():
                break
            if self.job_suspended():
                break
            ready = self.ready_goals()
            if not ready:
                await self.tick_dag_idle()
                if self.job_completed() or not self.ready_goals():
                    break
                continue
            for goal in list(ready):
                await on_ready(goal, self.turn)
                if self.job_completed() or self.job_suspended():
                    break
        return self.evaluation()


def write_evaluation_report(path: Path, reports: list[dict[str, Any]]) -> Path:
    """Write multi-scenario evaluation JSON for CI / human review."""
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "scenarios": reports,
        "passed": all(r.get("builtins_match_expected") for r in reports),
        "scenario_count": len(reports),
    }
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


def gr(matched_flag: bool, reasoning: str = "scripted") -> GuardResult:
    return GuardResult(matched=matched_flag, confidence=1.0, reasoning=reasoning)
