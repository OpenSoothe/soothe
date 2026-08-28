"""LLM-callable `request_plan_mode` tool."""

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
    """Log the request and return a confirmation message to the model."""
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
    """Build the `request_plan_mode` LLM-callable tool."""
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
