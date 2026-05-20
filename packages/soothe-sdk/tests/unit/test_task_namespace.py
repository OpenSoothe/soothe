"""Tests for Task-tool namespace binding helpers."""

from __future__ import annotations

from collections import deque

from soothe_sdk.ux.task_namespace import (
    _shorten_tool_call_id,
    maybe_bind_namespace,
    normalize_step_task_tool_call_id,
    normalize_unified_tool_call_id,
    parse_unified_tool_call_id,
    register_task_spawn_for_step,
    resolve_step_id_from_subgraph_tool,
    resolve_task_parent_for_unified_tool_id,
    resolve_task_parent_lookup,
    resolve_task_scope_for_namespace,
    row_key_for_subgraph_tool,
    scoped_subgraph_tool_key,
    step_level_parent_task_call_id,
    task_scope_task_idx,
    try_bind_namespace_to_unlinked_spawn,
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

    scope = ("YKF_02:s:task:0", "explore", "YKF-02")
    register_task_spawn_for_step(
        bindings,
        queue,
        spawns,
        scope,
        pending_unscoped_namespaces=pending_unscoped,
    )
    assert bindings[ns] == scope
    assert spawns["YKF-02"] == scope


def test_parallel_spawns_bind_one_namespace_per_register_when_interleaved() -> None:
    """Each spawn binds its namespace when only one is pending (parallel-safe)."""
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
            (f"{step_id.replace('-', '_')}:s:task:0", "explore", step_id),
            pending_unscoped_namespaces=pending_unscoped,
        )

    assert bindings[("tools:aaa",)][2] == "YKF-01"
    assert bindings[("tools:bbb",)][2] == "YKF-02"
    assert bindings[("tools:ccc",)][2] == "YKF-03"


def test_parallel_spawns_fifo_bind_when_multiple_namespaces_pending() -> None:
    """When multiple namespaces pending, FIFO binding pairs oldest namespace to first spawn."""
    bindings: dict[tuple[str, ...], tuple[str, str, str]] = {}
    queue: deque[tuple[str, str, str]] = deque()
    spawns: dict[str, tuple[str, str, str]] = {}
    pending_unscoped: deque[tuple[str, ...]] = deque()

    maybe_bind_namespace(
        bindings, queue, ("tools:aaa",), pending_unscoped_namespaces=pending_unscoped
    )
    maybe_bind_namespace(
        bindings, queue, ("tools:bbb",), pending_unscoped_namespaces=pending_unscoped
    )
    register_task_spawn_for_step(
        bindings,
        queue,
        spawns,
        ("YKF_01:s:task:0", "explore", "YKF-01"),
        pending_unscoped_namespaces=pending_unscoped,
    )
    # First namespace bound to first spawn (FIFO)
    assert bindings[("tools:aaa",)] == ("YKF_01:s:task:0", "explore", "YKF-01")
    assert ("tools:bbb",) not in bindings

    register_task_spawn_for_step(
        bindings,
        queue,
        spawns,
        ("YKF_02:s:task:0", "explore", "YKF-02"),
        pending_unscoped_namespaces=pending_unscoped,
    )
    # Second namespace bound to second spawn
    assert bindings[("tools:bbb",)] == ("YKF_02:s:task:0", "explore", "YKF-02")


def test_normalize_step_task_tool_call_id_embeds_step() -> None:
    assert normalize_step_task_tool_call_id("YKF-02", "functions.task:0") == "YKF_02:s:task:0"
    assert normalize_step_task_tool_call_id("YKF-02", "YKF_02:s:task:0") == "YKF_02:s:task:0"


def test_legacy_unified_formats_are_not_accepted() -> None:
    """Hyphen wire step or dot tool index are not unified."""
    assert parse_unified_tool_call_id("YKF-02:s:task:0") == ("", "", None, "YKF-02:s:task:0")
    assert parse_unified_tool_call_id("YKF_02:s:task.0") == ("", "", None, "YKF_02:s:task.0")
    assert normalize_unified_tool_call_id("YKF-02:s:task.0") == "YKF-02:s:task.0"


def test_resolve_step_id_from_subgraph_tool() -> None:
    assert resolve_step_id_from_subgraph_tool("YKF_02:t0:glob:1") == "YKF-02"
    assert resolve_step_id_from_subgraph_tool("YKF_02:s:task:0") == "YKF-02"


def test_step_level_parent_task_call_id() -> None:
    assert step_level_parent_task_call_id("ABC-01", 0) == "ABC_01:s:task:0"


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
    assert scoped_subgraph_tool_key((), "functions.grep:1") == "grep:1"


def test_resolve_task_scope_prefix_match() -> None:
    bindings = {
        ("tools:parent", "child"): ("tc-1", "explore", "EMD-01"),
    }
    scope = resolve_task_scope_for_namespace(
        bindings,
        ("tools:parent", "child", "grand"),
    )
    assert scope == ("tc-1", "explore", "EMD-01")


def test_parse_unified_tool_call_id_step_level() -> None:
    """Step-level unified IDs: {step_wire}:s:{tool}:{idx}"""
    assert parse_unified_tool_call_id("GHT_01:s:task:0") == (
        "GHT-01",
        "s",
        None,
        "task:0",
    )
    assert parse_unified_tool_call_id("EMD_02:s:read_file:1") == (
        "EMD-02",
        "s",
        None,
        "read_file:1",
    )


def test_parse_unified_tool_call_id_task_level() -> None:
    """Task-level unified IDs: {step_wire}:t{task_idx}:{tool}:{idx}"""
    assert parse_unified_tool_call_id("GHT_01:t0:read_file:1") == (
        "GHT-01",
        "t",
        0,
        "read_file:1",
    )
    assert parse_unified_tool_call_id("EMD_02:t2:grep:5") == (
        "EMD-02",
        "t",
        2,
        "grep:5",
    )


def test_parse_unified_tool_call_id_non_unified() -> None:
    """Non-unified IDs return empty type and step info."""
    assert parse_unified_tool_call_id("task:0") == ("", "", None, "task:0")
    assert parse_unified_tool_call_id("functions.grep:1") == (
        "",
        "",
        None,
        "functions.grep:1",
    )
    assert parse_unified_tool_call_id("call_abc123") == ("", "", None, "call_abc123")


def test_parse_unified_tool_call_id_empty() -> None:
    """Empty IDs return empty tuple."""
    assert parse_unified_tool_call_id("") == ("", "", None, "")


def test_scoped_subgraph_tool_key_passes_through_task_level_id() -> None:
    """Already-unified task-level ids are not double-prefixed."""
    unified = "GHT_01:t0:grep:2"
    assert (
        scoped_subgraph_tool_key(("tools:abc",), unified, task_scope=("tc", "explore", "GHT-01"))
        == unified
    )


def test_resolve_task_parent_lookup_prefers_task_card() -> None:
    step = object()
    task_card = object()
    scope = ("FJS_02:s:task:0", "explore", "FJS-02")
    parent = resolve_task_parent_lookup(
        scope,
        step_cards={"FJS-02": step},
        tool_display_by_call_id={"FJS_02:s:task:0": task_card},
    )
    assert parent is task_card


def test_resolve_task_parent_for_unified_task_level_id() -> None:
    task_card = object()
    spawns = {"FJS-02": ("FJS_02:s:task:0", "explore", "FJS-02")}
    parent = resolve_task_parent_for_unified_tool_id(
        "FJS_02:t0:grep:0",
        spawns_by_step=spawns,
        tool_display_by_call_id={"FJS_02:s:task:0": task_card},
    )
    assert parent is task_card
    assert (
        resolve_task_parent_for_unified_tool_id(
            "grep:1",
            spawns_by_step=spawns,
            tool_display_by_call_id={"FJS_02:s:task:0": task_card},
        )
        is None
    )


def test_shorten_tool_call_id_normalizes_provider_colon_index() -> None:
    assert _shorten_tool_call_id("functions.grep:0") == "grep:0"
    assert _shorten_tool_call_id("GHT_01:t0:read_file:1") == "read_file:1"


def test_row_key_for_subgraph_tool_unified_passthrough() -> None:
    unified = "FJS_02:t0:read_file:1"
    assert row_key_for_subgraph_tool(("tools:x",), unified) == unified
    legacy = row_key_for_subgraph_tool(
        ("tools:x",),
        "grep:0",
        task_scope=("tc", "explore", "FJS-02"),
    )
    assert legacy == "FJS_02:t0:grep:0"


def test_row_key_for_subgraph_tool_remaps_wrong_step_id() -> None:
    """Daemon sends task-level ID with wrong step_id - remap to bound task_scope."""
    # Daemon sent MFE_02:t0:grep:1 but namespace is bound to MFE-01's task
    wrong_tid = "MFE_02:t0:grep:1"
    bound_scope = ("MFE_01:s:task:0", "explore", "MFE-01")
    remapped = row_key_for_subgraph_tool(("tools:abc",), wrong_tid, task_scope=bound_scope)
    # Should remap to MFE-01 step with correct task_idx from scope
    assert remapped == "MFE_01:t0:grep:1"


def test_row_key_for_subgraph_tool_remaps_wrong_task_idx() -> None:
    """Daemon sends task-level ID with wrong task_idx - remap to bound scope's idx."""
    # Daemon sent MFE_01:t2:read_file:0 but namespace is bound to task_idx=0
    wrong_tid = "MFE_01:t2:read_file:0"
    bound_scope = ("MFE_01:s:task:0", "explore", "MFE-01")  # task_idx=0
    remapped = row_key_for_subgraph_tool(("tools:abc",), wrong_tid, task_scope=bound_scope)
    assert remapped == "MFE_01:t0:read_file:0"


def test_try_bind_namespace_to_unlinked_spawn_after_register() -> None:
    """Namespace arriving after spawn still binds when no other namespace took that spawn."""
    bindings: dict[tuple[str, ...], tuple[str, str, str]] = {}
    spawns: dict[str, tuple[str, str, str]] = {}
    pending: deque[tuple[str, ...]] = deque()
    scope = ("FJS_02:s:task:0", "explore", "FJS-02")
    register_task_spawn_for_step(
        bindings,
        deque(),
        spawns,
        scope,
        pending_unscoped_namespaces=pending,
    )
    ns = ("tools:late",)
    maybe_bind_namespace(bindings, deque(), ns, pending_unscoped_namespaces=pending)
    assert ns not in bindings
    assert try_bind_namespace_to_unlinked_spawn(
        bindings, spawns, ns, pending_unscoped_namespaces=pending
    )
    assert bindings[ns] == scope
    assert ns not in pending


def test_task_scope_task_idx_parses_from_task_tool_call_id() -> None:
    """Task index derived from TaskScope's task_tool_call_id element."""
    # Standard task delegation: ABC_01:s:task:0 → 0
    scope = ("ABC_01:s:task:0", "explore", "ABC-01")
    assert task_scope_task_idx(scope, "ABC-01") == 0

    # Task index 1: ABC_01:s:task:1 → 1
    scope = ("ABC_01:s:task:1", "research", "ABC-01")
    assert task_scope_task_idx(scope, "ABC-01") == 1

    # Task index 2: GHT_02:s:task:2 → 2
    scope = ("GHT_02:s:task:2", "plan", "GHT-02")
    assert task_scope_task_idx(scope, "GHT-02") == 2


def test_task_scope_task_idx_returns_zero_for_invalid_scope() -> None:
    """Zero returned when scope is empty or malformed."""
    # Empty scope
    assert task_scope_task_idx(None, "ABC-01") == 0
    assert task_scope_task_idx(("", "", ""), "ABC-01") == 0

    # Non-task tool_call_id (step-level tool, not task)
    scope = ("ABC_01:s:grep:0", "explore", "ABC-01")
    assert task_scope_task_idx(scope, "ABC-01") == 0

    # Non-unified tool_call_id
    scope = ("call_abc123", "explore", "ABC-01")
    assert task_scope_task_idx(scope, "ABC-01") == 0

    # Task-level ID (should be step-level)
    scope = ("ABC_01:t0:grep:0", "explore", "ABC-01")
    assert task_scope_task_idx(scope, "ABC-01") == 0
