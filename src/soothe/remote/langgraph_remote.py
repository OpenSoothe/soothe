"""LangGraphRemoteAgent -- RemoteAgentProtocol adapter for LangGraph RemoteGraph."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from typing import Any

logger = logging.getLogger(__name__)


class LangGraphRemoteAgent:
    """RemoteAgentProtocol implementation wrapping langgraph RemoteGraph.

    Requires `langgraph` to be installed with the remote client.
    """

    def __init__(self, url: str, graph_name: str = "agent") -> None:
        """Initialize with a LangGraph server URL.

        Args:
            url: The LangGraph server URL.
            graph_name: The graph name on the server.
        """
        self._url = url
        self._graph_name = graph_name

    async def invoke(self, task: str, context: dict[str, Any] | None = None) -> str:
        """Invoke the remote LangGraph agent."""
        try:
            from langgraph.pregel.remote import RemoteGraph

            graph = RemoteGraph(self._graph_name, url=self._url)
            result = await graph.ainvoke({"messages": [{"role": "user", "content": task}]})
            messages = result.get("messages", [])
            if messages:
                return str(messages[-1].get("content", ""))
            return str(result)
        except ImportError:
            logger.warning("langgraph remote not available")
            return "Error: langgraph remote not available"

    async def stream(self, task: str, context: dict[str, Any] | None = None) -> AsyncIterator[str]:
        """Stream is not fully supported; falls back to invoke."""
        result = await self.invoke(task, context)
        yield result

    async def health_check(self) -> bool:
        """Check if the remote server is reachable."""
        try:
            from langgraph.pregel.remote import RemoteGraph

            graph = RemoteGraph(self._graph_name, url=self._url)
            await graph.aget_graph()
        except Exception:  # noqa: BLE001
            return False
        else:
            return True
