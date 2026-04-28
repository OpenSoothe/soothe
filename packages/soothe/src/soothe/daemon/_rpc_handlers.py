"""Daemon RPC command handlers (RFC-404).

Structured command request/response handlers for slash commands.
Each handler executes a specific command and returns structured data.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


async def _handle_command_request(self, msg: dict[str, Any]) -> None:
    """Handle structured RPC command requests (RFC-404).

    Args:
        msg: Command request message with command, thread_id, params
    """
    command = msg.get("command")
    thread_id = msg.get("thread_id")
    params = msg.get("params", {})

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
            await self._send_command_response(command, error=f"Unknown command: {command}")
            return

        result = await handler(thread_id, params)
        await self._send_command_response(command, data=result)

    except Exception as exc:
        logger.exception(f"Command {command} failed")
        await self._send_command_response(command, error=str(exc))


async def _send_command_response(
    self, command: str, data: dict[str, Any] | None = None, error: str | None = None
) -> None:
    """Send structured command response (RFC-404).

    Args:
        command: Command name
        data: Response data (if successful)
        error: Error message (if failed)
    """
    response = {
        "type": "command_response",
        "command": command,
    }

    if data is not None:
        response["data"] = data
    if error is not None:
        response["error"] = error

    await self._broadcast(response)


# Individual command handlers


async def _cmd_clear(self, thread_id: str | None, params: dict) -> dict[str, Any]:
    """Clear thread history."""
    if not thread_id:
        raise ValueError("Thread ID required")

    # Clear thread state
    # TODO: Implement clear_thread in runner
    # await self._runner.clear_thread(thread_id)

    # Broadcast clear event to all clients
    await self._broadcast({"type": "clear", "thread_id": thread_id})

    return {"cleared": True, "thread_id": thread_id}


async def _cmd_exit(self, thread_id: str | None, params: dict) -> dict[str, Any]:
    """Stop thread and mark for exit."""
    if not thread_id:
        raise ValueError("Thread ID required")

    # Stop thread execution
    if self._query_running:
        await self._query_engine.cancel_current_query()

    # Mark thread as stopped
    await self._broadcast(
        {"type": "status", "state": "stopped", "thread_id": thread_id, "exit_requested": True}
    )

    return {"exit": True, "thread_id": thread_id}


async def _cmd_quit(self, thread_id: str | None, params: dict) -> dict[str, Any]:
    """Stop thread and mark for exit (same as exit)."""
    return await self._cmd_exit(thread_id, params)


async def _cmd_detach(self, thread_id: str | None, params: dict) -> dict[str, Any]:
    """Mark thread as detached."""
    if not thread_id:
        raise ValueError("Thread ID required")

    # Mark thread as detached (continues running)
    await self._broadcast(
        {
            "type": "status",
            "state": "detached",
            "thread_id": thread_id,
        }
    )

    return {"detached": True, "thread_id": thread_id}


async def _cmd_cancel(self, thread_id: str | None, params: dict) -> dict[str, Any]:
    """Cancel running query."""
    if not thread_id:
        raise ValueError("Thread ID required")

    if self._query_running:
        await self._query_engine.cancel_current_query()

    return {"cancelled": True, "thread_id": thread_id}


async def _cmd_memory(self, thread_id: str | None, params: dict) -> dict[str, Any]:
    """Query memory stats."""
    if not thread_id:
        raise ValueError("Thread ID required")

    stats = await self._runner.memory_stats()
    return {"memory_stats": stats}


async def _cmd_policy(self, thread_id: str | None, params: dict) -> dict[str, Any]:
    """Query policy profile."""
    policy_data = {
        "profile": self._runner.config.protocols.policy.profile,
        "planner_routing": self._runner.config.protocols.planner.routing,
        "memory_backend": self._runner.config.protocols.memory.backend,
    }
    return {"policy": policy_data}


async def _cmd_history(self, thread_id: str | None, params: dict) -> dict[str, Any]:
    """Query input history."""
    if not thread_id:
        raise ValueError("Thread ID required")

    # Get history from thread state
    st = self._thread_registry.get(thread_id)
    if st and hasattr(st, "input_history"):
        history = st.input_history.get_recent(20)
    else:
        history = []

    return {"history": history}


async def _cmd_config(self, thread_id: str | None, params: dict) -> dict[str, Any]:
    """Query configuration."""
    config_data = {
        "providers": [
            {"name": p.name, "models": list(p.models.keys()) if p.models else []}
            for p in (self._runner.config.providers or [])
        ],
        "workspace_dir": str(self._runner.config.workspace_dir or ""),
        "verbosity": str(self._runner.config.observability.verbosity),
    }
    return {"config": config_data}


async def _cmd_review(self, thread_id: str | None, params: dict) -> dict[str, Any]:
    """Query conversation history."""
    if not thread_id:
        raise ValueError("Thread ID required")

    # Get conversation from thread state
    state = await self._runner.aget_state({"configurable": {"thread_id": thread_id}})
    messages = state.values.get("messages", [])

    review = []
    for msg in messages[-20:]:
        review.append(
            {"timestamp": "", "type": msg.__class__.__name__, "content": str(msg.content)[:200]}
        )

    return {"review": review}


async def _cmd_plan(self, thread_id: str | None, params: dict) -> dict[str, Any]:
    """Query current plan."""
    if not thread_id:
        raise ValueError("Thread ID required")

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


async def _cmd_thread(self, thread_id: str | None, params: dict) -> dict[str, Any]:
    """Thread operations."""
    action = params.get("action")
    thread_id_param = params.get("id")

    if action == "archive":
        if not thread_id_param:
            raise ValueError("Thread ID required for archive")

        # TODO: Implement thread archiving in runner
        # await self._runner.archive_thread(thread_id_param)

        return {"archived": True, "thread_id": thread_id_param}
    else:
        raise ValueError(f"Unknown thread action: {action}")


async def _cmd_resume(self, thread_id: str | None, params: dict) -> dict[str, Any]:
    """Resume thread."""
    thread_id_param = params.get("thread_id")
    if not thread_id_param:
        raise ValueError("Thread ID required for resume")

    # TODO: Implement thread resuming
    # Similar to resume_thread WebSocket message handling

    return {"resumed": True, "thread_id": thread_id_param}


async def _cmd_autopilot_dashboard(self, thread_id: str | None, params: dict) -> dict[str, Any]:
    """Show autopilot dashboard."""
    if not thread_id:
        raise ValueError("Thread ID required")

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
