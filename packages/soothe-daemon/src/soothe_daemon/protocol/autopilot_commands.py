"""Shared autopilot action dispatch for protocol-1 RPC commands."""

from __future__ import annotations

from typing import Any


async def run_autopilot_action(
    service: Any,
    action: str,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Execute one autopilot command against an AutopilotService-like object.

    Args:
        service: Daemon autopilot service instance.
        action: Action name without the ``autopilot_`` prefix (e.g. ``status``).
        payload: Optional command fields (goal_id, description, ...).

    Returns:
        Result dict for the wire response ``result`` field.

    Raises:
        RuntimeError: Domain errors (missing service inputs, not found, etc.).
    """
    payload = payload or {}

    if action == "status":
        status = service.status()
        return {
            "state": "dreaming" if status.get("dreaming") else "active",
            "running": status.get("running", False),
            "dreaming": status.get("dreaming", False),
            "loop_pool": status.get("loop_pool", {}),
        }

    if action == "submit":
        description = payload.get("description", "")
        priority = payload.get("priority", 50)
        workspace = payload.get("workspace")
        rail_id = payload.get("rail_id")
        verification_rules = payload.get("verification_rules")
        if not description:
            raise RuntimeError("description is required")
        goal = await service.submit_task(
            description,
            priority=priority,
            workspace=workspace,
            rail_id=rail_id if isinstance(rail_id, str) else None,
            verification_rules=(
                verification_rules.strip()
                if isinstance(verification_rules, str) and verification_rules.strip()
                else None
            ),
        )
        return {
            "status": "submitted",
            "goal_id": goal.id,
            "rail_id": goal.rail_id,
        }

    if action == "list_goals":
        goals = await service.list_goals()
        return {
            "goals": [g.model_dump(mode="json") for g in goals],
            "source": "autopilot_service",
        }

    if action == "get_goal":
        goal_id = payload.get("goal_id")
        goal = await service.get_goal(goal_id)
        if goal:
            return {"goal": goal.model_dump(mode="json"), "source": "autopilot_service"}
        raise RuntimeError("Goal not found")

    if action == "cancel_goal":
        goal_id = payload.get("goal_id")
        cancelled = await service.cancel_goal(goal_id, reason="ws_command")
        if cancelled is None:
            raise RuntimeError("Goal not found")
        return {"status": "cancelled", "goal_id": cancelled.id, "new_status": cancelled.status}

    if action == "cancel_all":
        result = await service.cancel_all_open_goals(reason="ws_command")
        return {
            "status": "cancelled",
            "cancelled_count": result.get("cancelled_count", 0),
            "goal_ids": result.get("goal_ids", []),
        }

    if action == "resume":
        goal_id = payload.get("goal_id")
        if not goal_id:
            raise RuntimeError("goal_id is required")
        try:
            reactivated = await service.resume_job(goal_id)
        except ValueError as exc:
            raise RuntimeError(str(exc)) from exc
        if reactivated is None:
            raise RuntimeError("Goal not found")
        return {
            "status": "reactivated",
            "goal_id": goal_id,
            "new_status": reactivated.status,
        }

    if action == "wake":
        await service.wake_from_dreaming(trigger="ws_command")
        return {"status": "wake_sent"}

    if action == "dream":
        await service.force_dream()
        return {"status": "dream_sent"}

    if action == "list_jobs":
        goals = await service.list_goals()
        jobs = [g for g in goals if g.parent_id is None]
        return {
            "jobs": [j.model_dump(mode="json") for j in jobs],
            "source": "autopilot_service",
        }

    if action == "get_job":
        job_id = payload.get("job_id")
        job = await service.get_goal(job_id)
        if not job:
            raise RuntimeError("Job not found")
        if job.parent_id is not None:
            raise RuntimeError("Not a root goal (job)")
        dag = await service.dag_snapshot(job_id)
        nodes = dag.get("nodes", [])
        active = sum(1 for n in nodes if n.get("status") == "active")
        completed = sum(1 for n in nodes if n.get("status") in ("completed", "validated"))
        return {
            "job": job.model_dump(mode="json"),
            "dag": dag,
            "active_goals": active,
            "completed_goals": completed,
            "total_goals": len(nodes),
            "source": "autopilot_service",
        }

    if action == "top":
        include_terminal = bool(payload.get("include_terminal", False))
        return await service.top_snapshot(include_terminal=include_terminal)

    raise RuntimeError(f"Unknown autopilot action: {action}")
