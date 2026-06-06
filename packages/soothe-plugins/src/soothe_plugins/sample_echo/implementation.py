"""Minimal LangGraph subagent for integration testing (no LLM)."""

from __future__ import annotations

from typing import Annotated, Any, TypedDict

from langchain_core.messages import AIMessage, HumanMessage
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages


class EchoState(TypedDict):
    """Graph state: conversation messages only."""

    messages: Annotated[list[Any], add_messages]


def _echo_node(state: EchoState) -> dict[str, Any]:
    """Return an assistant message echoing the last human input."""
    text = ""
    for msg in reversed(state.get("messages", [])):
        if isinstance(msg, HumanMessage):
            text = str(msg.content)
            break
    body = f"[sample_echo] {text!r}"
    return {"messages": [AIMessage(content=body)]}


def create_echo_subagent_spec() -> dict[str, Any]:
    """Build a compiled subgraph spec for deepagents ``task`` delegation.

    Returns:
        Subagent dict with ``name``, ``description``, and ``runnable``.
    """
    graph = StateGraph(EchoState)
    graph.add_node("echo", _echo_node)
    graph.add_edge(START, "echo")
    graph.add_edge("echo", END)
    compiled = graph.compile()
    return {
        "name": "sample_echo",
        "description": (
            "Test-only community subagent that echoes the last user message. "
            "Use for plugin and resolver integration checks."
        ),
        "runnable": compiled,
    }
