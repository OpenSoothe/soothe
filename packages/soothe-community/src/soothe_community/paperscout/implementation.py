"""PaperScout subagent implementation.

Creates a LangGraph workflow for the PaperScout agent that:
1. Validates configuration (profile_analysis)
2. Fetches papers from ArXiv and Zotero (data_collection)
3. Ranks papers by relevance (relevance_assessment)
4. Generates TLDR and email content (content_generation)
5. Sends email notification (communication)
"""

from __future__ import annotations

import logging
from typing import Any

from langgraph.graph import END, START, StateGraph

from soothe_sdk import PersistStore
from soothe_community.paperscout.nodes import make_nodes
from soothe_community.paperscout.state import AgentState, PaperScoutConfig

logger = logging.getLogger(__name__)


def create_paperscout_graph(
    store: PersistStore,
    user_id: str,
) -> StateGraph:
    """Create the PaperScout workflow graph.

    Args:
        store: PersistStore for state persistence.
        user_id: User identifier for storage keys.

    Returns:
        Compiled LangGraph StateGraph.
    """
    # Create nodes
    nodes = make_nodes(store, user_id)

    # Create graph
    graph = StateGraph(AgentState)

    # Add nodes
    graph.add_node("profile_analysis", nodes["profile_analysis"])
    graph.add_node("data_collection", nodes["data_collection"])
    graph.add_node("relevance_assessment", nodes["relevance_assessment"])
    graph.add_node("content_generation", nodes["content_generation"])
    graph.add_node("communication", nodes["communication"])

    # Add edges (linear workflow)
    graph.add_edge(START, "profile_analysis")
    graph.add_edge("profile_analysis", "data_collection")
    graph.add_edge("data_collection", "relevance_assessment")
    graph.add_edge("relevance_assessment", "content_generation")
    graph.add_edge("content_generation", "communication")
    graph.add_edge("communication", END)

    return graph


def create_paperscout_subagent(
    config: PaperScoutConfig,
    store: PersistStore,
    user_id: str = "default",
) -> dict[str, Any]:
    """Create a PaperScout subagent.

    Args:
        config: PaperScout configuration.
        store: PersistStore for state persistence.
        user_id: User identifier for storage keys.

    Returns:
        Subagent dict compatible with deepagents:
        {
            "name": "paperscout",
            "description": "...",
            "runnable": CompiledStateGraph,
        }
    """
    # Create the graph
    graph = create_paperscout_graph(store, user_id)

    # Compile the graph
    compiled = graph.compile()

    return {
        "name": "paperscout",
        "description": (
            "ArXiv paper recommendation agent that delivers personalized daily "
            "paper recommendations by analyzing your Zotero library and ranking "
            "newly published papers by relevance. Use for research paper discovery "
            "and automated literature monitoring."
        ),
        "runnable": compiled,
        "config": config,
    }


__all__ = [
    "create_paperscout_graph",
    "create_paperscout_subagent",
]
