"""Goal directive processing mixin for autonomous runner (RFC-0007 §5.4).

Handles goal DAG mutations, directive application, iteration record
storage, and continuation synthesis.  Mixed into ``AutonomousMixin``.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from langchain_core.messages import HumanMessage

from soothe.protocols.context import ContextEntry

logger = logging.getLogger(__name__)


class GoalDirectivesMixin:
    """Goal directive processing and helpers for autonomous execution (RFC-0007 §5.4).

    Mixed into ``AutonomousMixin`` -- all ``self.*`` attributes are defined
    on the concrete ``SootheRunner`` class.
    """

    async def _store_iteration_record(self, record: Any, _thread_id: str) -> None:
        """Persist an iteration record via ContextProtocol (RFC-0007)."""
        if not self._context:
            return
        try:
            await self._context.ingest(
                ContextEntry(
                    source="iteration_journal",
                    content=record.model_dump_json(),
                    tags=["iteration_record", f"iteration:{record.iteration}"],
                    importance=0.9,
                )
            )
        except Exception:
            logger.debug("Failed to store iteration record", exc_info=True)

    async def _synthesize_continuation(
        self,
        original_goal: str,
        records: list[Any],
        plan: Any | None,
    ) -> str:
        """Generate the next iteration's input via a lightweight LLM call (RFC-0007)."""
        try:
            model = self._config.create_chat_model("fast")
        except Exception:
            try:
                model = self._config.create_chat_model("default")
            except Exception:
                logger.debug("Failed to create model for continuation synthesis")
                return original_goal

        history = "\n".join(f"- Iteration {r.iteration}: {r.reflection_assessment[:100]}" for r in records[-5:])
        plan_text = ""
        if plan:
            plan_text = f"\nRevised plan: {plan.goal}\nSteps: " + "; ".join(s.description for s in plan.steps[:5])

        prompt = (
            f"You are managing an autonomous agent. The original goal is:\n{original_goal}\n\n"
            f"History of iterations:\n{history}\n{plan_text}\n\n"
            "Generate a concise instruction for the next iteration. "
            "Focus on what specifically to do next based on what was learned. "
            "Do not repeat actions already completed."
        )

        try:
            response = await model.ainvoke([HumanMessage(content=prompt)])
            return str(response.content).strip() or original_goal
        except Exception:
            logger.debug("Continuation synthesis failed, reusing original goal", exc_info=True)
            return original_goal

    async def _check_goal_dag_consistency(self, goal: Any) -> bool:
        """Check if goal's dependencies are still met after DAG mutations (RFC-0007 §5.5).

        Returns:
            True if goal should be aborted (dependencies now unmet), False otherwise.
        """
        if not self._goal_engine:
            return False

        for dep_id in goal.depends_on:
            dep_goal = await self._goal_engine.get_goal(dep_id)
            if not dep_goal or dep_goal.status != "completed":
                logger.info(
                    "Goal %s dependency %s is not completed (status: %s)",
                    goal.id,
                    dep_id,
                    dep_goal.status if dep_goal else "missing",
                )
                return True

        return False

    async def _process_goal_directives(
        self,
        directives: list[Any],
        current_goal: Any,
    ) -> dict[str, Any]:
        """Process goal management directives from reflection (RFC-0007 §5.4)."""
        if not self._goal_engine:
            logger.warning("Goal engine not available, skipping directives")
            return {"error": "goal_engine_unavailable"}

        changes: dict[str, list] = {
            "created": [],
            "decomposed": [],
            "priority_adjusted": [],
            "dependencies_added": [],
            "failed": [],
            "completed": [],
            "rejected": [],
        }

        for directive in directives:
            try:
                result = await self._apply_goal_directive(directive, current_goal)
                if result.get("applied"):
                    changes[result["category"]].append(result["summary"])
                else:
                    changes["rejected"].append(
                        {
                            "directive": directive.action,
                            "reason": result.get("reason"),
                        }
                    )
            except Exception as e:
                logger.exception("Failed to apply directive: %s", directive)
                changes["rejected"].append(
                    {
                        "directive": directive.action,
                        "reason": str(e),
                    }
                )

        if any(
            changes[cat]
            for cat in [
                "created",
                "decomposed",
                "priority_adjusted",
                "dependencies_added",
                "failed",
                "completed",
            ]
        ):
            logger.info(self._goal_engine._format_goal_dag())

        return changes

    async def _apply_goal_directive(
        self,
        directive: Any,
        current_goal: Any,
    ) -> dict[str, Any]:
        """Apply a single goal directive with validation (RFC-0007 §5.4)."""
        if directive.action == "create":
            return await self._apply_create_directive(directive)

        if directive.action == "adjust_priority":
            return await self._apply_priority_directive(directive)

        if directive.action == "add_dependency":
            return await self._apply_dependency_directive(directive)

        if directive.action == "decompose":
            return await self._apply_decompose_directive(directive, current_goal)

        if directive.action == "fail":
            return await self._apply_fail_directive(directive)

        if directive.action == "complete":
            return await self._apply_complete_directive(directive)

        return {"applied": False, "reason": f"Unknown action: {directive.action}"}

    async def _apply_create_directive(self, directive: Any) -> dict[str, Any]:
        """Apply a CREATE goal directive."""
        total_goals = len(await self._goal_engine.list_goals())
        active_goals = len([g for g in await self._goal_engine.list_goals() if g.status in ("pending", "active")])

        max_total = getattr(self._config.autonomous, "max_total_goals", 50)
        if total_goals >= max_total:
            return {"applied": False, "reason": f"Max goals limit reached ({max_total})"}

        if active_goals >= self._concurrency.max_parallel_goals * 3:
            return {"applied": False, "reason": f"Too many active goals ({active_goals})"}

        new_goal = await self._goal_engine.create_goal(
            description=directive.description,
            priority=directive.priority or 50,
            parent_id=directive.parent_id,
            max_retries=self._config.autonomous.max_retries if hasattr(self._config, "autonomous") else 2,
        )

        if directive.depends_on:
            try:
                await self._goal_engine.add_dependencies(new_goal.id, directive.depends_on)
            except ValueError as e:
                logger.warning("Failed to add dependencies to new goal: %s", e)

        logger.info(
            "Created goal %s via reflection: %s (priority=%d)",
            new_goal.id,
            directive.description[:50],
            new_goal.priority,
        )

        return {
            "applied": True,
            "category": "created",
            "summary": {
                "goal_id": new_goal.id,
                "description": directive.description[:100],
                "priority": new_goal.priority,
                "parent_id": directive.parent_id,
            },
        }

    async def _apply_priority_directive(self, directive: Any) -> dict[str, Any]:
        """Apply an ADJUST_PRIORITY goal directive."""
        if not directive.goal_id or directive.priority is None:
            return {"applied": False, "reason": "goal_id and priority required"}

        goal = await self._goal_engine.get_goal(directive.goal_id)
        if not goal:
            return {"applied": False, "reason": f"Goal {directive.goal_id} not found"}

        old_priority = goal.priority
        goal.priority = max(0, min(100, directive.priority))
        goal.updated_at = datetime.now(UTC)

        logger.info("Adjusted goal %s priority: %d -> %d", directive.goal_id, old_priority, goal.priority)

        return {
            "applied": True,
            "category": "priority_adjusted",
            "summary": {
                "goal_id": directive.goal_id,
                "old_priority": old_priority,
                "new_priority": goal.priority,
            },
        }

    async def _apply_dependency_directive(self, directive: Any) -> dict[str, Any]:
        """Apply an ADD_DEPENDENCY goal directive."""
        if not directive.goal_id or not directive.depends_on:
            return {"applied": False, "reason": "goal_id and depends_on required"}

        try:
            await self._goal_engine.add_dependencies(directive.goal_id, directive.depends_on)
        except ValueError as e:
            return {"applied": False, "reason": str(e)}

        return {
            "applied": True,
            "category": "dependencies_added",
            "summary": {
                "goal_id": directive.goal_id,
                "new_dependencies": directive.depends_on,
            },
        }

    async def _apply_decompose_directive(self, directive: Any, current_goal: Any) -> dict[str, Any]:
        """Apply a DECOMPOSE goal directive."""
        target_id = directive.goal_id or current_goal.id
        target_goal = await self._goal_engine.get_goal(target_id)

        if not target_goal:
            return {"applied": False, "reason": f"Goal {target_id} not found"}

        if target_goal.status != "pending":
            return {"applied": False, "reason": f"Goal {target_id} is {target_goal.status}"}

        sub_goal = await self._goal_engine.create_goal(
            description=directive.description,
            priority=directive.priority or target_goal.priority,
            parent_id=target_id,
            max_retries=target_goal.max_retries,
        )

        logger.info("Decomposed goal %s into sub-goal %s: %s", target_id, sub_goal.id, directive.description[:50])

        return {
            "applied": True,
            "category": "decomposed",
            "summary": {
                "parent_goal_id": target_id,
                "sub_goal_id": sub_goal.id,
                "description": directive.description[:100],
            },
        }

    async def _apply_fail_directive(self, directive: Any) -> dict[str, Any]:
        """Apply a FAIL goal directive."""
        if not directive.goal_id:
            return {"applied": False, "reason": "goal_id required"}

        await self._goal_engine.fail_goal(
            directive.goal_id,
            error=directive.rationale or "Failed via reflection directive",
            allow_retry=False,
        )

        logger.warning("Failed goal %s via reflection: %s", directive.goal_id, directive.rationale)

        return {
            "applied": True,
            "category": "failed",
            "summary": {
                "goal_id": directive.goal_id,
                "reason": directive.rationale,
            },
        }

    async def _apply_complete_directive(self, directive: Any) -> dict[str, Any]:
        """Apply a COMPLETE goal directive."""
        if not directive.goal_id:
            return {"applied": False, "reason": "goal_id required"}

        await self._goal_engine.complete_goal(directive.goal_id)

        logger.info("Completed goal %s via reflection: %s", directive.goal_id, directive.rationale)

        return {
            "applied": True,
            "category": "completed",
            "summary": {
                "goal_id": directive.goal_id,
                "reason": directive.rationale,
            },
        }
