"""LLM-callable ``request_plan_mode`` tool.

When the model invokes this tool, it emits a user-confirmation event. On
confirmation, ``LoopState.pending_plan_mode`` is set so the *next* goal
dispatch runs in plan mode (``interaction_mode=plan``). The current
goal's graph is already selected and cannot swap mid-run, so the flag
takes effect on the next goal via ``enter_loop``.

Renamed from ``require_plan`` to avoid collision with the autopilot-rails
builtin (``builtins_exec.py``, ``catalog.py``, ``guards.py``,
``interpreter.py``, ``wave_plan.py``, ``service.py``).
"""

from __future__ import annotations

import logging

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class _RequestPlanModeArgs(BaseModel):
    reason: str = Field(
        default="",
        description="Why plan mode is being requested (shown to the user in the confirmation prompt).",
    )


def _run_request_plan_mode(reason: str = "") -> str:
    """Set the pending plan-mode flag and return a confirmation message.

    The actual user-confirmation flow is handled by the clarification /
    TUI event channel. This tool's return tells the model the request
    was registered and the next goal will enter plan mode pending user
    confirmation.
    """
    reason_text = (reason or "").strip()
    log_reason = reason_text[:200] if reason_text else "(no reason given)"
    logger.info("[request_plan_mode] LLM requested plan mode: %s", log_reason)
    return (
        "Plan mode requested. The operator will be asked to confirm. "
        "If confirmed, the next goal will run in plan mode (read-only tools). "
        "Continue with the current goal normally."
    )


async def _arun_request_plan_mode(reason: str = "") -> str:
    return _run_request_plan_mode(reason)


def build_request_plan_mode_tool() -> StructuredTool:
    """Build the ``request_plan_mode`` LLM-callable tool."""
    return StructuredTool.from_function(
        name="request_plan_mode",
        description=(
            "Request to switch to plan mode for the next goal. "
            "Plan mode restricts tools to read-only (ls, read_file, file_info, "
            "glob, grep) so you can research the codebase and produce a "
            "detailed implementation plan before any changes are made. "
            "The operator must confirm before plan mode is activated. "
            "Use this when the task is complex enough to warrant planning first."
        ),
        func=_run_request_plan_mode,
        coroutine=_arun_request_plan_mode,
        args_schema=_RequestPlanModeArgs,
        infer_schema=False,
    )
