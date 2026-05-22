"""Daemon RPC command handlers (RFC-404).

Structured command request/response handlers for slash commands.
Each handler executes a specific command and returns structured data.

IG-408 naming:
    - Wire / clients: ``loop_id`` (AgentLoop subscription scope).
    - First positional argument to each ``_cmd_*`` handler: ``checkpoint_thread_id`` —
      the LangGraph / durability checkpoint key (``configurable.thread_id``) after
      ``bind_execution_thread_for_loop``; not a client routing id.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


async def _handle_command_request(self, msg: dict[str, Any]) -> None:
    """Handle structured RPC command requests (RFC-404).

    Args:
        msg: Command request with ``command``, optional ``params``, and ``loop_id``
            (required; set by the loop input worker after bind, or supplied by tests with
            a runner that already has ``current_thread_id``).
    """
    request_id = msg.get("request_id")
    command = msg.get("command")
    lid = str(msg.get("loop_id") or "").strip()
    params = msg.get("params", {})

    if not lid:
        await self._send_command_response(
            command or "",
            error="command_request requires loop_id",
            request_id=request_id,
            loop_id=None,
        )
        return

    checkpoint_thread_id = ""
    if self._runner is not None:
        checkpoint_thread_id = str(self._runner.current_thread_id or "").strip()

    if not checkpoint_thread_id:
        from soothe_daemon.loop_isolation import bind_execution_thread_for_loop

        try:
            checkpoint_thread_id = await bind_execution_thread_for_loop(self, lid)
        except Exception as exc:
            logger.warning("command_request: failed to bind loop %s: %s", lid[:16], exc)
            await self._send_command_response(
                command or "",
                error=f"Could not resolve execution context for loop: {exc}",
                request_id=request_id,
                loop_id=lid,
            )
            return

    resolved_checkpoint = checkpoint_thread_id
    loop_id = lid

    try:
        # Dispatch to handlers
        handler_map = {
            "clear": self._cmd_clear,
            "exit": self._cmd_exit,
            "quit": self._cmd_quit,
            "detach": self._cmd_detach,
            "cancel": self._cmd_cancel,
            "memory": self._cmd_memory,
            "policy": self._cmd_policy,
            "history": self._cmd_history,
            "config": self._cmd_config,
            "review": self._cmd_review,
            "plan": self._cmd_plan,
            "thread": self._cmd_thread,
            "resume": self._cmd_resume,
            "autopilot_dashboard": self._cmd_autopilot_dashboard,
        }

        handler = handler_map.get(command)
        if not handler:
            await self._send_command_response(
                command or "",
                error=f"Unknown command: {command!r}",
                request_id=request_id,
                loop_id=loop_id,
            )
            return

        result = await handler(resolved_checkpoint, params, loop_id=loop_id)
        await self._send_command_response(
            command, data=result, request_id=request_id, loop_id=loop_id
        )

    except Exception as exc:
        logger.exception(f"Command {command} failed")
        await self._send_command_response(
            command or "",
            error=str(exc),
            request_id=request_id,
            loop_id=loop_id,
        )


async def _send_command_response(
    self,
    command: str,
    data: dict[str, Any] | None = None,
    error: str | None = None,
    *,
    request_id: str | None = None,
    loop_id: str | None = None,
) -> None:
    """Send structured command response (RFC-404).

    Args:
        command: Command name
        data: Response data (if successful)
        error: Error message (if failed)
        request_id: Echo client correlation id when present (WebSocket ``request_response``).
    """
    response: dict[str, Any] = {
        "type": "command_response",
        "command": command,
    }

    if data is not None:
        response["data"] = data
    if error is not None:
        response["error"] = error
    if request_id is not None:
        response["request_id"] = request_id
    if loop_id:
        response["loop_id"] = loop_id

    await self._broadcast(response)


# Individual command handlers


async def _cmd_clear(
    self, checkpoint_thread_id: str | None, params: dict, *, loop_id: str | None = None
) -> dict[str, Any]:
    """Clear conversation history for the bound checkpoint (loop-scoped broadcast)."""
    if not checkpoint_thread_id:
        raise ValueError("Active loop required")

    # Clear thread state
    # TODO: Implement clear_thread in runner
    # await self._runner.clear_thread(checkpoint_thread_id)

    lid = str(loop_id or "").strip()
    if lid:
        await self._broadcast({"type": "clear", "loop_id": lid})
    else:
        logger.warning("RPC clear: missing loop_id; not routing clear event to loop subscribers")

    return {"cleared": True}


async def _cmd_exit(
    self, checkpoint_thread_id: str | None, params: dict, *, loop_id: str | None = None
) -> dict[str, Any]:
    """Stop execution and mark for exit (cancel targets the subscribed loop)."""
    if not checkpoint_thread_id:
        raise ValueError("Active loop required")

    lid = str(loop_id or "").strip() or (
        self._thread_registry.get_thread_loop(checkpoint_thread_id) or ""
    )
    if self._query_running and lid:
        await self._query_engine.cancel_loop(lid)
    elif self._query_running and not lid:
        logger.warning("RPC exit: active query but no loop_id; not cancelling (avoid broad cancel)")

    await self._broadcast({"type": "status", "state": "stopped", "exit_requested": True})

    return {"exit": True}


async def _cmd_quit(
    self, checkpoint_thread_id: str | None, params: dict, *, loop_id: str | None = None
) -> dict[str, Any]:
    """Same as ``_cmd_exit``."""
    return await self._cmd_exit(checkpoint_thread_id, params, loop_id=loop_id)


async def _cmd_detach(
    self, checkpoint_thread_id: str | None, params: dict, *, loop_id: str | None = None
) -> dict[str, Any]:
    """Mark the client session detached (loop-scoped status when ``loop_id`` is known)."""
    if not checkpoint_thread_id:
        raise ValueError("Active loop required")

    lid = str(loop_id or "").strip()
    if lid:
        await self._broadcast({"type": "status", "state": "detached", "loop_id": lid})
    else:
        await self._broadcast({"type": "status", "state": "detached"})

    return {"detached": True}


async def _cmd_cancel(
    self, checkpoint_thread_id: str | None, params: dict, *, loop_id: str | None = None
) -> dict[str, Any]:
    """Cancel the running query for the subscribed loop."""
    if not checkpoint_thread_id:
        raise ValueError("Active loop required")

    lid = str(loop_id or "").strip() or (
        self._thread_registry.get_thread_loop(checkpoint_thread_id) or ""
    )
    if self._query_running and lid:
        await self._query_engine.cancel_loop(lid)
    elif self._query_running and not lid:
        logger.warning(
            "RPC cancel: active query but no loop_id; not cancelling (avoid broad cancel)"
        )

    return {"cancelled": True}


async def _cmd_memory(
    self, checkpoint_thread_id: str | None, params: dict, *, loop_id: str | None = None
) -> dict[str, Any]:
    """Query memory stats."""
    if not checkpoint_thread_id:
        raise ValueError("Active loop required")

    stats = await self._runner.memory_stats()
    return {"memory_stats": stats}


async def _cmd_policy(
    self, checkpoint_thread_id: str | None, params: dict, *, loop_id: str | None = None
) -> dict[str, Any]:
    """Query policy profile."""
    policy_data = {
        "profile": self._runner.config.protocols.policy.profile,
        "planner_routing": self._runner.config.protocols.planner.routing,
        "memory_backend": self._runner.config.protocols.memory.backend,
    }
    return {"policy": policy_data}


async def _cmd_history(
    self, checkpoint_thread_id: str | None, params: dict, *, loop_id: str | None = None
) -> dict[str, Any]:
    """Query input history for the active checkpoint."""
    if not checkpoint_thread_id:
        raise ValueError("Active loop required")

    # Get history from thread state
    st = self._thread_registry.get(checkpoint_thread_id)
    if st and hasattr(st, "input_history"):
        history = st.input_history.get_recent(20)
    else:
        history = []

    return {"history": history}


async def _cmd_config(
    self, checkpoint_thread_id: str | None, params: dict, *, loop_id: str | None = None
) -> dict[str, Any]:
    """Query configuration."""
    config_data = {
        "providers": [
            {"name": p.name, "models": list(p.models.keys()) if p.models else []}
            for p in (self._runner.config.providers or [])
        ],
        "verbosity": str(self._runner.config.observability.verbosity),
    }
    return {"config": config_data}


async def _cmd_review(
    self, checkpoint_thread_id: str | None, params: dict, *, loop_id: str | None = None
) -> dict[str, Any]:
    """Query conversation history from checkpoint state."""
    if not checkpoint_thread_id:
        raise ValueError("Active loop required")

    # Get conversation from thread state
    state = await self._runner.aget_state({"configurable": {"thread_id": checkpoint_thread_id}})
    messages = state.values.get("messages", [])

    review = []
    for msg in messages[-20:]:
        review.append(
            {"timestamp": "", "type": msg.__class__.__name__, "content": str(msg.content)[:200]}
        )

    return {"review": review}


async def _cmd_plan(
    self, checkpoint_thread_id: str | None, params: dict, *, loop_id: str | None = None
) -> dict[str, Any]:
    """Query current plan for the active checkpoint."""
    if not checkpoint_thread_id:
        raise ValueError("Active loop required")

    # Get current plan from runner
    plan = None
    if hasattr(self._runner, "_current_plan"):
        plan = self._runner._current_plan

    plan_data = None
    if plan:
        plan_data = {
            "goal": plan.goal,
            "reasoning": plan.reasoning,
            "general_activity": plan.general_activity,
            "steps": [
                {
                    "description": step.description,
                    "status": step.status,
                    "depends_on": list(step.depends_on or []),
                    "current_activity": step.current_activity,
                }
                for step in plan.steps
            ],
        }

    return {"plan": plan_data}


async def _cmd_thread(
    self, checkpoint_thread_id: str | None, params: dict, *, loop_id: str | None = None
) -> dict[str, Any]:
    """Durability / checkpoint operations (params use checkpoint ids, not ``loop_id``)."""
    action = params.get("action")
    target_checkpoint_id = params.get("id")

    if action == "archive":
        if not target_checkpoint_id:
            raise ValueError("Checkpoint id required for archive (params.id)")

        # TODO: Implement thread archiving in runner
        # await self._runner.archive_thread(target_checkpoint_id)

        return {"archived": True, "checkpoint_thread_id": target_checkpoint_id}
    else:
        raise ValueError(f"Unknown thread action: {action}")


async def _cmd_resume(
    self, checkpoint_thread_id: str | None, params: dict, *, loop_id: str | None = None
) -> dict[str, Any]:
    """Resume target loop (``params.loop_id``)."""
    target_loop = params.get("loop_id")
    if not target_loop:
        raise ValueError("loop_id required for resume")

    # TODO: Implement thread resuming
    # Similar to resume_thread WebSocket message handling

    return {"resumed": True, "loop_id": target_loop}


async def _cmd_autopilot_dashboard(
    self, checkpoint_thread_id: str | None, params: dict, *, loop_id: str | None = None
) -> dict[str, Any]:
    """Show autopilot dashboard for the bound loop/checkpoint."""
    if not checkpoint_thread_id:
        raise ValueError("Active loop required")

    # TODO: Get autopilot state from runner
    dashboard = {
        "status": "idle",
        "iterations": 0,
        "goals_completed": 0,
        "goals_active": 0,
        "active_goals": [],
    }

    return {"autopilot_dashboard": dashboard}


# Export handlers for mixin
__all__ = [
    "_handle_command_request",
    "_send_command_response",
    "_cmd_clear",
    "_cmd_exit",
    "_cmd_quit",
    "_cmd_detach",
    "_cmd_cancel",
    "_cmd_memory",
    "_cmd_policy",
    "_cmd_history",
    "_cmd_config",
    "_cmd_review",
    "_cmd_plan",
    "_cmd_thread",
    "_cmd_resume",
    "_cmd_autopilot_dashboard",
]
