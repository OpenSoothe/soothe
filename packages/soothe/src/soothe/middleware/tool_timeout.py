"""Compatibility shim for migrated tool-timeout middleware.

The implementation now lives in ``soothe_deepagents.middleware.tool_timeout``.
Soothe runtime wiring uses the deepagents class directly; this module remains
only to preserve imports from ``soothe.middleware.tool_timeout``.
"""

from __future__ import annotations

from soothe_deepagents.middleware.tool_timeout import ToolTimeoutMiddleware

__all__ = ["ToolTimeoutMiddleware"]
