"""Tests for Task-tool namespace binding helpers (IG-334, parallel step scope)."""

from __future__ import annotations

from collections import deque

from soothe_sdk.ux.task_namespace import (
    maybe_bind_namespace,
    register_task_spawn_for_step,
    resolve_task_scope_for_namespace,
    scoped_subgraph_tool_key,
)


def test_register_task_spawn_binds_deferred_namespace_for_step() -> None:
    """Namespaces that arrive before spawn attach to the correct step, not FIFO head."""
    bindings: dict[tuple[str, ...], tuple[str, str, str]] = {}
    queue: deque[tuple[str, str, str]] = deque()
    spawns: dict[str, tuple[str, str, str]] = {}
    pending: dict[str, list[tuple[str, ...]]] = {}
    ns = ("tools:explore-a",)

    maybe_bind_namespace(
        bindings,
        queue,
        ns,
        active_step_id="YKF-02",
        spawns_by_step=spawns,
        pending_namespaces_by_step=pending,
    )
    assert ns not in bindings
    assert pending["YKF-02"] == [ns]

    scope = ("functions.task:0", "explore", "YKF-02")
    register_task_spawn_for_step(bindings, queue, spawns, pending, scope)
    assert bindings[ns] == scope
    assert spawns["YKF-02"] == scope


def test_maybe_bind_uses_active_step_when_spawn_registered() -> None:
    bindings: dict[tuple[str, ...], tuple[str, str, str]] = {}
    queue: deque[tuple[str, str, str]] = deque()
    spawns = {"YKF-03": ("functions.task:0", "explore", "YKF-03")}
    ns = ("tools:explore-c",)

    maybe_bind_namespace(
        bindings,
        queue,
        ns,
        active_step_id="YKF-03",
        spawns_by_step=spawns,
        pending_namespaces_by_step={},
    )
    assert bindings[ns] == spawns["YKF-03"]


def test_parallel_spawns_do_not_steal_via_fifo_when_step_scoped() -> None:
    """Three step-scoped spawns bind three namespaces without cross-talk."""
    bindings: dict[tuple[str, ...], tuple[str, str, str]] = {}
    queue: deque[tuple[str, str, str]] = deque()
    spawns: dict[str, tuple[str, str, str]] = {}
    pending: dict[str, list[tuple[str, ...]]] = {}

    for step_id, ns in (
        ("YKF-01", ("tools:aaa",)),
        ("YKF-02", ("tools:bbb",)),
        ("YKF-03", ("tools:ccc",)),
    ):
        maybe_bind_namespace(
            bindings,
            queue,
            ns,
            active_step_id=step_id,
            spawns_by_step=spawns,
            pending_namespaces_by_step=pending,
        )
        register_task_spawn_for_step(
            bindings,
            queue,
            spawns,
            pending,
            ("functions.task:0", "explore", step_id),
        )

    assert bindings[("tools:aaa",)][2] == "YKF-01"
    assert bindings[("tools:bbb",)][2] == "YKF-02"
    assert bindings[("tools:ccc",)][2] == "YKF-03"


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
