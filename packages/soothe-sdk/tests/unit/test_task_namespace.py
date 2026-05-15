"""Tests for Task-tool namespace binding helpers."""

from __future__ import annotations

from collections import deque

from soothe_sdk.ux.task_namespace import (
    maybe_bind_namespace,
    register_task_spawn_for_step,
    resolve_task_scope_for_namespace,
    scoped_subgraph_tool_key,
)


def test_register_task_spawn_binds_deferred_unscoped_namespace() -> None:
    """Namespaces that arrive before spawn attach in FIFO order per register."""
    bindings: dict[tuple[str, ...], tuple[str, str, str]] = {}
    queue: deque[tuple[str, str, str]] = deque()
    spawns: dict[str, tuple[str, str, str]] = {}
    pending_unscoped: deque[tuple[str, ...]] = deque()
    ns = ("tools:explore-a",)

    maybe_bind_namespace(
        bindings,
        queue,
        ns,
        pending_unscoped_namespaces=pending_unscoped,
    )
    assert ns not in bindings
    assert list(pending_unscoped) == [ns]

    scope = ("functions.task:0", "explore", "YKF-02")
    register_task_spawn_for_step(
        bindings,
        queue,
        spawns,
        scope,
        pending_unscoped_namespaces=pending_unscoped,
    )
    assert bindings[ns] == scope
    assert spawns["YKF-02"] == scope


def test_parallel_spawns_bind_namespaces_in_order() -> None:
    """Three step-scoped spawns bind three namespaces without cross-talk."""
    bindings: dict[tuple[str, ...], tuple[str, str, str]] = {}
    queue: deque[tuple[str, str, str]] = deque()
    spawns: dict[str, tuple[str, str, str]] = {}
    pending_unscoped: deque[tuple[str, ...]] = deque()

    for step_id, ns in (
        ("YKF-01", ("tools:aaa",)),
        ("YKF-02", ("tools:bbb",)),
        ("YKF-03", ("tools:ccc",)),
    ):
        maybe_bind_namespace(
            bindings,
            queue,
            ns,
            pending_unscoped_namespaces=pending_unscoped,
        )
        register_task_spawn_for_step(
            bindings,
            queue,
            spawns,
            ("functions.task:0", "explore", step_id),
            pending_unscoped_namespaces=pending_unscoped,
        )

    assert bindings[("tools:aaa",)][2] == "YKF-01"
    assert bindings[("tools:bbb",)][2] == "YKF-02"
    assert bindings[("tools:ccc",)][2] == "YKF-03"


def test_headless_maybe_bind_uses_spawn_queue_fifo() -> None:
    """Clients without unscoped deferral bind the next queued task spawn."""
    bindings: dict[tuple[str, ...], tuple[str, str, str]] = {}
    queue: deque[tuple[str, str, str]] = deque()
    queue.append(("tc-1", "explore", ""))
    maybe_bind_namespace(bindings, queue, ("tools:x",))
    assert bindings[("tools:x",)] == ("tc-1", "explore", "")


def test_scoped_subgraph_tool_key_is_unique_per_namespace() -> None:
    a = scoped_subgraph_tool_key(("tools:aaa",), "functions.grep:1")
    b = scoped_subgraph_tool_key(("tools:bbb",), "functions.grep:1")
    assert a != b
    assert scoped_subgraph_tool_key((), "functions.grep:1") == "functions.grep:1"


def test_resolve_task_scope_prefix_match() -> None:
    bindings = {
        ("tools:parent", "child"): ("tc-1", "explore", "EMD-01"),
    }
    scope = resolve_task_scope_for_namespace(
        bindings,
        ("tools:parent", "child", "grand"),
    )
    assert scope == ("tc-1", "explore", "EMD-01")
