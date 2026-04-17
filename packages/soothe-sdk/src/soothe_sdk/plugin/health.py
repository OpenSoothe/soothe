"""Plugin health status model."""

from typing import Any, Literal

from pydantic import BaseModel, Field


class PluginHealth(BaseModel):
    """Health check result for a plugin.

    Attributes:
        status: Health status (healthy, degraded, unhealthy).
        message: Optional diagnostic message.
        details: Additional health metrics or diagnostics.
    """

    status: Literal["healthy", "degraded", "unhealthy"]
    message: str = ""
    details: dict[str, Any] = Field(default_factory=dict)
