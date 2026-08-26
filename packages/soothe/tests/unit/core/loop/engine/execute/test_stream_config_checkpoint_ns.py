"""The execute stream config must not inherit the parent graph's checkpoint
coordinates — doing so nests the CoreAgent under the StrangeLoop execute-node
task namespace, where interrupts are unreachable by ``Command(resume)``
(IG-763, loops 573f / d491). The config-injected checkpointer must be
preserved: the execution twin graph is compiled without one (lazy pool init)
and receives it via the config (loop 776b regression)."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

from soothe.config import SootheConfig
from soothe.sloop.engine.execute.executor import Executor
from soothe.sloop.utils.graph_config import strip_parent_checkpoint_coordinates


def test_strip_parent_checkpoint_coordinates() -> None:
    checkpointer = object()
    config: dict[str, Any] = {
        "configurable": {
            "thread_id": "fork-1",
            "checkpoint_ns": "execute:abc123",
            "checkpoint_id": "ck-1",
            "checkpoint_map": {"a": 1},
            "__pregel_checkpointer": checkpointer,
            "soothe_step_expected_output": "x",
        },
        "callbacks": ["cb"],
    }
    out = strip_parent_checkpoint_coordinates(config)
    conf = out["configurable"]
    assert conf["thread_id"] == "fork-1"
    assert conf["soothe_step_expected_output"] == "x"
    assert "checkpoint_ns" not in conf
    assert "checkpoint_id" not in conf
    assert "checkpoint_map" not in conf
    # The checkpointer must survive: the execution twin has none compiled.
    assert conf["__pregel_checkpointer"] is checkpointer
    # Tracing callbacks are untouched.
    assert out["callbacks"] == ["cb"]


def test_strip_handles_missing_configurable() -> None:
    assert strip_parent_checkpoint_coordinates({}) == {}


def test_execute_stream_config_strips_parent_checkpoint_ns(
    monkeypatch: Any,
) -> None:
    """End-to-end for the executor's langfuse merge: the ambient StrangeLoop
    execute-node config (carrying checkpoint_ns and the shared checkpointer)
    must not leak its checkpoint coordinates into the CoreAgent stream
    config, while the checkpointer and tracing callbacks must."""
    checkpointer = object()
    contaminated_parent: dict[str, Any] = {
        "configurable": {
            "thread_id": "strange-loop-thread",
            "checkpoint_ns": "execute:task-uuid",
            "checkpoint_id": "ck-9",
            "__pregel_checkpointer": checkpointer,
        },
        "callbacks": ["parent-cb"],
    }
    monkeypatch.setattr("langgraph.config.get_config", lambda: contaminated_parent)

    executor = Executor(MagicMock(), config=SootheConfig())
    base = {"configurable": {"thread_id": "fork-1", "soothe_step_expected_output": "x"}}

    merged = executor._executor_langfuse_merge_for_stream(base, thread_id="fork-1")

    conf = merged["configurable"]
    assert conf["thread_id"] == "fork-1"
    assert "checkpoint_ns" not in conf
    assert "checkpoint_id" not in conf
    assert "checkpoint_map" not in conf
    # The checkpointer flows through (execution twin has none compiled).
    assert conf["__pregel_checkpointer"] is checkpointer
    # Tracing callbacks from the parent are preserved.
    assert merged.get("callbacks") == ["parent-cb"]
