"""Tests for Task-tool namespace binding helpers."""

from __future__ import annotations

from collections import deque

from soothe_sdk.ux.task_namespace import (
    _shorten_tool_call_id,
    normalize_main_task_delegation_id,
    normalize_step_task_tool_call_id,
    normalize_unified_tool_call_id,
    parse_unified_tool_call_id,
    prune_bound_pending_namespaces,
    register_task_spawn_for_step,
    resolve_task_parent_lookup,
    resolve_task_scope_for_namespace,
    resolve_task_scope_for_subgraph_tool,
    row_key_for_subgraph_tool,
    scoped_subgraph_tool_key,
    step_level_parent_task_call_id,
    task_scope_task_idx,
    try_bind_namespace_from_tool_call_id,
)


def test_prune_bound_pending_namespaces_removes_linked() -> None:
    bindings: dict[tuple[str, ...], tuple[str, str, str]] = {
        ("tools:a",): ("S_01:s:task:0", "deep_research", "S-01"),
    }
    pending: deque[tuple[str, ...]] = deque(
        [("tools:a",), ("tools:b",), ("tools:a",), ("tools:c",)]
    )
    prune_bound_pending_namespaces(bindings, pending)
    assert list(pending) == [("tools:b",), ("tools:c",)]


def test_register_task_spawn_for_step_records_spawn() -> None:
    """Namespaces that arrive before spawn attach in FIFO order per register."""
    bindings: dict[tuple[str, ...], tuple[str, str, str]] = {}
    queue: deque[tuple[str, str, str]] = deque()
    spawns: dict[str, tuple[str, str, str]] = {}

    scope = ("YKF_02:s:task:0", "deep_research", "YKF-02")
    register_task_spawn_for_step(
        bindings,
        queue,
        spawns,
        scope,
    )
    assert spawns["YKF-02"] == scope


def test_parallel_spawns_bind_via_unified_tool_call_id() -> None:
    """Parallel spawns bind namespaces using unified tool_call_id matching."""
    bindings: dict[tuple[str, ...], tuple[str, str, str]] = {}
    queue: deque[tuple[str, str, str]] = deque()
    spawns: dict[str, tuple[str, str, str]] = {}

    # Register spawns for steps
    for step_id in ("YKF-01", "YKF-02", "YKF-03"):
        scope = (f"{step_id.replace('-', '_')}:s:task:0", "deep_research", step_id)
        register_task_spawn_for_step(bindings, queue, spawns, scope)

    # Bind using unified tool_call_id from subgraph tools
    assert try_bind_namespace_from_tool_call_id(
        bindings, spawns, ("tools:aaa",), "YKF_01:t0:grep:0"
    )
    assert try_bind_namespace_from_tool_call_id(
        bindings, spawns, ("tools:bbb",), "YKF_02:t0:glob:1"
    )
    assert try_bind_namespace_from_tool_call_id(
        bindings, spawns, ("tools:ccc",), "YKF_03:t0:read_file:2"
    )

    assert bindings[("tools:aaa",)] == ("YKF_01:s:task:0", "deep_research", "YKF-01")
    assert bindings[("tools:bbb",)] == ("YKF_02:s:task:0", "deep_research", "YKF-02")
    assert bindings[("tools:ccc",)] == ("YKF_03:s:task:0", "deep_research", "YKF-03")


def test_normalize_main_task_delegation_id_remaps_task_level_opaque_prefix() -> None:
    """Step-level task delegations stamped as ``t{n}:tool-…`` normalize to ``s:task:{n}``."""
    assert (
        normalize_main_task_delegation_id("ZCH-01", "ZCH_01:t0:tool-abc123", tool_name="task")
        == "ZCH_01:s:task:0"
    )
    assert (
        normalize_main_task_delegation_id("WAV-01", "WAV_01:t1:tool-xyz", tool_name="task")
        == "WAV_01:s:task:1"
    )


def test_resolve_task_scope_for_subgraph_tool_no_steal_from_spawns_by_step() -> None:
    """``t1`` tools must not fall back to ``spawns_by_step`` (often ``task:0``)."""
    spawns_by_step = {"WAV-01": ("WAV_01:s:task:0", "deep_research", "WAV-01")}
    spawns_by_task = {
        "WAV_01:s:task:0": ("WAV_01:s:task:0", "deep_research", "WAV-01"),
    }
    scope = resolve_task_scope_for_subgraph_tool(
        "WAV_01:t1:grep:0",
        spawns_by_step,
        spawns_by_task,
    )
    assert scope is None


def test_normalize_step_task_tool_call_id_embeds_step() -> None:
    assert normalize_step_task_tool_call_id("YKF-02", "functions.task:0") == "YKF_02:s:task:0"
    assert normalize_step_task_tool_call_id("YKF-02", "YKF_02:s:task:0") == "YKF_02:s:task:0"


def test_normalize_step_task_tool_call_id_does_not_remap_foreign_step() -> None:
    """Another step's task id must not be forced onto the current step card."""
    foreign = "YKF_02:s:task:0"
    assert normalize_step_task_tool_call_id("YKF-01", foreign) == foreign


def test_is_inner_subgraph_task_tool_id() -> None:
    from soothe_sdk.ux.task_namespace import is_inner_subgraph_task_tool_id

    assert is_inner_subgraph_task_tool_id("YKF_02:t0:task:0")
    assert not is_inner_subgraph_task_tool_id("YKF_02:s:task:0")
    assert not is_inner_subgraph_task_tool_id("YKF_02:t0:glob:1")


def test_try_bind_namespace_rejects_inner_task_id() -> None:
    from soothe_sdk.ux.task_namespace import is_inner_subgraph_task_tool_id

    bindings: dict[tuple[str, ...], tuple[str, str, str]] = {}
    spawns = {"YKF-02": ("YKF_02:s:task:0", "deep_research", "YKF-02")}
    assert not try_bind_namespace_from_tool_call_id(
        bindings, spawns, ("tools:aaa",), "YKF_02:t0:task:0"
    )
    assert ("tools:aaa",) not in bindings
    _ = is_inner_subgraph_task_tool_id


def test_register_task_spawn_for_step_keeps_step_level_spawn() -> None:
    bindings: dict[tuple[str, ...], tuple[str, str, str]] = {}
    queue: deque[tuple[str, str, str]] = deque()
    spawns: dict[str, tuple[str, str, str]] = {}
    register_task_spawn_for_step(
        bindings,
        queue,
        spawns,
        ("YKF_02:s:task:0", "deep_research", "YKF-02"),
    )
    register_task_spawn_for_step(
        bindings,
        queue,
        spawns,
        ("YKF_02:t0:task:0", "deep_research", "YKF-02"),
    )
    assert spawns["YKF-02"][0] == "YKF_02:s:task:0"


def test_try_bind_namespace_rebinds_on_definitive_tool_id() -> None:
    bindings: dict[tuple[str, ...], tuple[str, str, str]] = {
        ("tools:aaa",): ("YKF_02:s:task:0", "deep_research", "YKF-02"),
    }
    spawns = {
        "YKF-02": ("YKF_02:s:task:0", "deep_research", "YKF-02"),
        "YKF-03": ("YKF_03:s:task:0", "deep_research", "YKF-03"),
    }
    assert try_bind_namespace_from_tool_call_id(
        bindings, spawns, ("tools:aaa",), "YKF_03:t0:glob:0"
    )
    assert bindings[("tools:aaa",)] == ("YKF_03:s:task:0", "deep_research", "YKF-03")


def test_legacy_unified_formats_are_not_accepted() -> None:
    """Hyphen wire step is rejected; only the underscore wire form marks a unified id.

    Tool_info is treated as opaque after the leading ``{step_wire}:{type}:`` marker,
    so ``YKF_02:s:task.0`` is now a valid unified id with tool_info ``task.0`` — the
    parser doesn't enforce a structured ``name:idx`` form anymore.
    """
    assert parse_unified_tool_call_id("YKF-02:s:task:0") == ("", "", None, "YKF-02:s:task:0")
    assert normalize_unified_tool_call_id("YKF-02:s:task.0") == "YKF-02:s:task.0"


def test_step_level_parent_task_call_id() -> None:
    assert step_level_parent_task_call_id("ABC-01", 0) == "ABC_01:s:task:0"


def test_scoped_subgraph_tool_key_is_unique_per_namespace() -> None:
    a = scoped_subgraph_tool_key(("tools:aaa",), "functions.grep:1")
    b = scoped_subgraph_tool_key(("tools:bbb",), "functions.grep:1")
    assert a != b
    assert scoped_subgraph_tool_key((), "functions.grep:1") == "grep:1"


def test_resolve_task_scope_prefix_match() -> None:
    bindings = {
        ("tools:parent", "child"): ("tc-1", "deep_research", "EMD-01"),
    }
    scope = resolve_task_scope_for_namespace(
        bindings,
        ("tools:parent", "child", "grand"),
    )
    assert scope == ("tc-1", "deep_research", "EMD-01")


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


def test_parse_unified_tool_call_id_opaque_provider_step_level() -> None:
    """Provider ids without a ``:idx`` suffix still recover the step id.

    Kimi-style providers stamp tool_call_ids like ``tool-{uuid}``. The executor
    wraps them as ``ZKE_01:s:tool-{uuid}`` (3 colon segments). The leading wire
    fragment + ``s`` marker is enough to recover the step id; tool_info is the
    raw provider fragment.
    """
    raw = "ZKE_01:s:tool-f9af17a88ccf476e948e7a094fca8795"
    assert parse_unified_tool_call_id(raw) == (
        "ZKE-01",
        "s",
        None,
        "tool-f9af17a88ccf476e948e7a094fca8795",
    )


def test_parse_unified_tool_call_id_opaque_provider_task_level() -> None:
    """Task-level ids with opaque tool_info also parse correctly."""
    raw = "ABC_03:t1:call_xyz"
    assert parse_unified_tool_call_id(raw) == ("ABC-03", "t", 1, "call_xyz")


def test_parse_unified_tool_call_id_round_trip_opaque_id() -> None:
    """Opaque tool_info round-trips through normalize without losing the step id."""
    raw = "ZKE_01:s:tool-f9af17a88ccf476e948e7a094fca8795"
    assert normalize_unified_tool_call_id(raw) == raw
    assert _shorten_tool_call_id(raw) == "tool-f9af17a88ccf476e948e7a094fca8795"


def test_scoped_subgraph_tool_key_passes_through_task_level_id() -> None:
    """Already-unified task-level ids are not double-prefixed."""
    unified = "GHT_01:t0:grep:2"
    assert (
        scoped_subgraph_tool_key(
            ("tools:abc",), unified, task_scope=("tc", "deep_research", "GHT-01")
        )
        == unified
    )


def test_resolve_task_parent_lookup_prefers_task_card() -> None:
    step = object()
    task_card = object()
    scope = ("FJS_02:s:task:0", "deep_research", "FJS-02")
    parent = resolve_task_parent_lookup(
        scope,
        step_cards={"FJS-02": step},
        tool_display_by_call_id={"FJS_02:s:task:0": task_card},
    )
    assert parent is task_card


def test_shorten_tool_call_id_normalizes_provider_colon_index() -> None:
    assert _shorten_tool_call_id("functions.grep:0") == "grep:0"
    assert _shorten_tool_call_id("GHT_01:t0:read_file:1") == "read_file:1"


def test_row_key_for_subgraph_tool_unified_passthrough() -> None:
    unified = "FJS_02:t0:read_file:1"
    assert row_key_for_subgraph_tool(("tools:x",), unified) == unified
    legacy = row_key_for_subgraph_tool(
        ("tools:x",),
        "grep:0",
        task_scope=("tc", "deep_research", "FJS-02"),
    )
    assert legacy == "FJS_02:t0:grep:0"


def test_row_key_for_subgraph_tool_remaps_wrong_step_id() -> None:
    """Daemon sends task-level ID with wrong step_id - remap to bound task_scope."""
    # Daemon sent MFE_02:t0:grep:1 but namespace is bound to MFE-01's task
    wrong_tid = "MFE_02:t0:grep:1"
    bound_scope = ("MFE_01:s:task:0", "deep_research", "MFE-01")
    remapped = row_key_for_subgraph_tool(("tools:abc",), wrong_tid, task_scope=bound_scope)
    # Should remap to MFE-01 step with correct task_idx from scope
    assert remapped == "MFE_01:t0:grep:1"


def test_row_key_for_subgraph_tool_remaps_wrong_task_idx() -> None:
    """Daemon sends task-level ID with wrong task_idx - remap to bound scope's idx."""
    # Daemon sent MFE_01:t2:read_file:0 but namespace is bound to task_idx=0
    wrong_tid = "MFE_01:t2:read_file:0"
    bound_scope = ("MFE_01:s:task:0", "deep_research", "MFE-01")  # task_idx=0
    remapped = row_key_for_subgraph_tool(("tools:abc",), wrong_tid, task_scope=bound_scope)
    assert remapped == "MFE_01:t0:read_file:0"


def test_task_scope_task_idx_parses_from_task_tool_call_id() -> None:
    """Task index derived from TaskScope's task_tool_call_id element."""
    # Standard task delegation: ABC_01:s:task:0 → 0
    scope = ("ABC_01:s:task:0", "deep_research", "ABC-01")
    assert task_scope_task_idx(scope, "ABC-01") == 0

    # Task index 1: ABC_01:s:task:1 → 1
    scope = ("ABC_01:s:task:1", "deep_research", "ABC-01")
    assert task_scope_task_idx(scope, "ABC-01") == 1

    # Task index 2: GHT_02:s:task:2 → 2
    scope = ("GHT_02:s:task:2", "plan", "GHT-02")
    assert task_scope_task_idx(scope, "GHT-02") == 2


def test_resolve_task_scope_for_subgraph_tool_uses_spawns_by_task_id() -> None:
    """Second ``task:N`` on one step must not steal bindings from the first."""
    spawns_by_step = {"WAV-01": ("WAV_01:s:task:1", "deep_research", "WAV-01")}
    spawns_by_task = {
        "WAV_01:s:task:0": ("WAV_01:s:task:0", "deep_research", "WAV-01"),
        "WAV_01:s:task:1": ("WAV_01:s:task:1", "deep_research", "WAV-01"),
    }
    scope0 = resolve_task_scope_for_subgraph_tool(
        "WAV_01:t0:grep:0",
        spawns_by_step,
        spawns_by_task,
    )
    scope1 = resolve_task_scope_for_subgraph_tool(
        "WAV_01:t1:grep:0",
        spawns_by_step,
        spawns_by_task,
    )
    assert scope0 == ("WAV_01:s:task:0", "deep_research", "WAV-01")
    assert scope1 == ("WAV_01:s:task:1", "deep_research", "WAV-01")


def test_register_second_task_on_same_step_preserves_first_spawn() -> None:
    bindings: dict[tuple[str, ...], tuple[str, str, str]] = {}
    queue: deque[tuple[str, str, str]] = deque()
    spawns_by_step: dict[str, tuple[str, str, str]] = {}
    spawns_by_task: dict[str, tuple[str, str, str]] = {}
    register_task_spawn_for_step(
        bindings,
        queue,
        spawns_by_step,
        ("WAV_01:s:task:0", "deep_research", "WAV-01"),
        spawns_by_task_id=spawns_by_task,
    )
    register_task_spawn_for_step(
        bindings,
        queue,
        spawns_by_step,
        ("WAV_01:s:task:1", "deep_research", "WAV-01"),
        spawns_by_task_id=spawns_by_task,
    )
    assert spawns_by_step["WAV-01"] == ("WAV_01:s:task:0", "deep_research", "WAV-01")
    assert spawns_by_task["WAV_01:s:task:0"][1] == "deep_research"
    assert spawns_by_task["WAV_01:s:task:1"][1] == "deep_research"


def test_try_bind_namespace_uses_spawns_by_task_id_for_parallel_tasks() -> None:
    bindings: dict[tuple[str, ...], tuple[str, str, str]] = {}
    spawns_by_step = {"WAV-01": ("WAV_01:s:task:1", "deep_research", "WAV-01")}
    spawns_by_task = {
        "WAV_01:s:task:0": ("WAV_01:s:task:0", "deep_research", "WAV-01"),
        "WAV_01:s:task:1": ("WAV_01:s:task:1", "deep_research", "WAV-01"),
    }
    assert try_bind_namespace_from_tool_call_id(
        bindings,
        spawns_by_step,
        ("tools:first",),
        "WAV_01:t0:grep:0",
        spawns_by_task_id=spawns_by_task,
    )
    assert bindings[("tools:first",)] == ("WAV_01:s:task:0", "deep_research", "WAV-01")


def test_task_scope_task_idx_returns_zero_for_invalid_scope() -> None:
    """Zero returned when scope is empty or malformed."""
    # Empty scope
    assert task_scope_task_idx(None, "ABC-01") == 0
    assert task_scope_task_idx(("", "", ""), "ABC-01") == 0

    # Non-task tool_call_id (step-level tool, not task)
    scope = ("ABC_01:s:grep:0", "deep_research", "ABC-01")
    assert task_scope_task_idx(scope, "ABC-01") == 0

    # Non-unified tool_call_id
    scope = ("call_abc123", "deep_research", "ABC-01")
    assert task_scope_task_idx(scope, "ABC-01") == 0

    # Task-level ID (should be step-level)
    scope = ("ABC_01:t0:grep:0", "deep_research", "ABC-01")
    assert task_scope_task_idx(scope, "ABC-01") == 0
