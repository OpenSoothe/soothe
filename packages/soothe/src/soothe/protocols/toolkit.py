"""ToolkitProtocol -- runtime-agnostic interface for tool collections."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from langchain_core.tools import BaseTool


@runtime_checkable
class ToolkitProtocol(Protocol):
    """Protocol for toolkits -- collections of related tools.

    Each toolkit provides a cohesive set of tools for a specific domain.
    Toolkits are instantiated by the resolver or plugin system with
    configuration parameters, and return BaseTool instances via get_tools().
    """

    def get_tools(self) -> list[BaseTool]:
        """Return all tools in this toolkit.

        Returns:
            List of langchain BaseTool instances.
        """
        ...
