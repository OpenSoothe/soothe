"""Loop graph must attach a durable checkpointer when CoreAgent has one."""

from __future__ import annotations

import logging
from unittest.mock import MagicMock

from langgraph.checkpoint.memory import MemorySaver

from soothe.sloop.orchestrator.builder import build_strange_loop_graph
from soothe.sloop.orchestrator.checkpointer import core_agent_checkpointer


def test_build_strange_loop_graph_attaches_core_agent_checkpointer() -> None:
    saver = MemorySaver()
    ctx = MagicMock()
    ctx.strange_loop.core_agent.graph.checkpointer = saver
    # Explicit: already-materialized agent (MagicMock.is_materialized is truthy).
    ctx.strange_loop.core_agent.is_materialized = True

    compiled = build_strange_loop_graph(ctx)

    assert compiled.checkpointer is saver


def test_build_strange_loop_graph_warns_without_checkpointer(caplog) -> None:
    ctx = MagicMock()
    ctx.strange_loop.core_agent.is_materialized = True
    ctx.strange_loop.core_agent.graph.checkpointer = None

    with caplog.at_level(logging.WARNING, logger="soothe.sloop.orchestrator.builder"):
        compiled = build_strange_loop_graph(ctx)

    assert compiled.checkpointer is None or compiled.checkpointer is False
    assert any("without checkpointer" in rec.message for rec in caplog.records)


def test_core_agent_checkpointer_skips_unmaterialized_lazy_agent() -> None:
    """Must not sync-materialize LazyCoreAgent (would omit the async saver)."""
    strange_loop = MagicMock()
    agent = MagicMock()
    agent.is_materialized = False

    def _graph_should_not_be_touched(_self: object) -> object:
        raise AssertionError("LazyCoreAgent.graph must not be accessed before materialize")

    type(agent).graph = property(_graph_should_not_be_touched)
    strange_loop.core_agent = agent

    assert core_agent_checkpointer(strange_loop) is None
