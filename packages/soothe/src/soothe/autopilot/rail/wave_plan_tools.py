"""Agent-facing ``record_wave_plan`` tool factory (IG-700).

Persists fan-out policy via ``RailBuiltinExecutor.record_wave_plan`` so agents
never need the job-scoped filesystem path.
"""

from __future__ import annotations

from typing import Any

from soothe.autopilot.rail.builtins_exec import RailBuiltinExecutor


def make_record_wave_plan_tool(executor: RailBuiltinExecutor, job_id: str) -> Any:
    """Build a LangChain tool bound to one job's rail executor.

    Returns:
        A ``StructuredTool`` named ``record_wave_plan``.
    """
    from langchain_core.tools import StructuredTool
    from pydantic import BaseModel, Field

    class _Args(BaseModel):
        wave_modules: list[str] = Field(
            default_factory=list,
            description="Independent ownership unit names for the next maker wave",
        )
        rationale: str | None = Field(default=None, description="Why this partition")
        independence: str | None = Field(
            default=None,
            description="Independence constraint (e.g. disjoint write-sets)",
        )
        max_waves: int | None = Field(default=None, ge=1, le=32)

    async def _run(
        wave_modules: list[str] | None = None,
        rationale: str | None = None,
        independence: str | None = None,
        max_waves: int | None = None,
    ) -> str:
        plan = await executor.record_wave_plan(
            job_id,
            wave_modules=list(wave_modules or []),
            rationale=rationale,
            independence=independence,
            max_waves=max_waves,
        )
        if plan is None:
            return "Failed to record wave plan (job not bound or empty modules)"
        names = plan.resolved_module_names()
        return f"Recorded wave plan with {len(names)} modules: {', '.join(names)}"

    return StructuredTool.from_function(
        coroutine=_run,
        name="record_wave_plan",
        description=(
            "Record the LLM fan-out plan for this rail job (module names and "
            "rationale). The host persists it under the job's private state — "
            "do not write fan-out JSON into the project workspace."
        ),
        args_schema=_Args,
    )
