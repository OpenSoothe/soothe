"""Wire-safe protocol schemas for WebSocket communication.

These schemas are used in daemon-CLI communication via WebSocket protocol.
They're defined in SDK so both daemon and CLI can use them without daemon
runtime dependency in CLI.

This module is part of Phase 1 of IG-174: CLI import violations fix.

Note: These are simplified wire-safe versions. Full protocol implementations
are in soothe.protocols.planner (daemon-side).
"""

from pydantic import BaseModel, Field


class PlanStep(BaseModel):
    """Wire-safe plan step schema for WebSocket protocol."""

    step_id: str = Field(description="Unique identifier for this step")
    description: str = Field(description="Human-readable step description")
    status: str = Field(
        default="pending", description="Step status: pending/running/completed/failed"
    )
    result: str | None = Field(default=None, description="Step execution result")
    error: str | None = Field(default=None, description="Error message if failed")


class Plan(BaseModel):
    """Wire-safe plan schema for WebSocket protocol."""

    plan_id: str = Field(description="Unique identifier for this plan")
    goal: str = Field(description="The goal this plan addresses")
    steps: list[PlanStep] = Field(default_factory=list, description="Ordered list of steps")
    status: str = Field(
        default="created", description="Plan status: created/executing/completed/failed"
    )


class ToolOutput(BaseModel):
    """Wire-safe tool output schema for WebSocket protocol.

    Used to structure tool results for rendering in CLI.
    """

    tool_name: str = Field(description="Name of the tool that produced output")
    output: str = Field(description="Tool output content")
    error: str | None = Field(default=None, description="Error if tool failed")
    metadata: dict = Field(default_factory=dict, description="Additional metadata")


__all__ = [
    "Plan",
    "PlanStep",
    "ToolOutput",
]
