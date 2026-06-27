"""Tests for execute stream namespace classification."""

from __future__ import annotations

from soothe_sdk.ux.execute_namespace import (
    is_execute_namespace_key,
    is_parallel_branch_namespace,
    is_root_execute_namespace_key,
    is_step_level_execute_namespace_key,
)


def test_is_execute_namespace_key() -> None:
    assert is_execute_namespace_key(("execute:abc",))
    assert is_execute_namespace_key(("execute:abc/1",))
    assert not is_execute_namespace_key(())
    assert not is_execute_namespace_key(("execute:abc", "tools:xyz"))
    assert not is_execute_namespace_key(("tools:xyz",))
    # IG-514: Two-element namespaces are NOT single execute namespace
    assert not is_execute_namespace_key(("execute:abc", "1"))


def test_is_root_execute_namespace_key() -> None:
    assert is_root_execute_namespace_key(("execute:abc",))
    assert not is_root_execute_namespace_key(("execute:abc/1",))
    assert not is_root_execute_namespace_key(("execute:abc", "tools:xyz"))
    # IG-514: Parallel branches are not root execute
    assert not is_root_execute_namespace_key(("execute:abc", "0"))


def test_is_step_level_execute_namespace_key() -> None:
    assert is_step_level_execute_namespace_key(("execute:abc",))
    assert is_step_level_execute_namespace_key(("execute:abc/1",))
    assert not is_step_level_execute_namespace_key(("tools:sub",))
    # IG-514: Parallel branches ARE step-level (s: prefix)
    assert is_step_level_execute_namespace_key(("execute:abc-uuid", "0"))
    assert is_step_level_execute_namespace_key(("execute:abc-uuid", "1"))
    # Nested subgraph is NOT step-level
    assert not is_step_level_execute_namespace_key(("execute:abc", "tools:xyz"))
    assert not is_step_level_execute_namespace_key(("tools:xyz", "sub"))


def test_is_parallel_branch_namespace() -> None:
    """IG-514: Parallel branch namespace detection."""
    # Valid parallel branches (execute:* + integer)
    assert is_parallel_branch_namespace(("execute:run_id", "0"))
    assert is_parallel_branch_namespace(("execute:run_id", "1"))
    assert is_parallel_branch_namespace(("execute:9ca81bee-c3e0-6af9", "2"))

    # NOT parallel branches
    assert not is_parallel_branch_namespace(("execute:run_id",))  # Single element
    assert not is_parallel_branch_namespace(("execute:run_id", "tools:sub"))  # tools namespace
    assert not is_parallel_branch_namespace(("execute:run_id", "abc"))  # Non-integer
    assert not is_parallel_branch_namespace(("tools:sub", "1"))  # Not execute prefix
    assert not is_parallel_branch_namespace(("execute:run_id", "1", "extra"))  # Three elements
    assert not is_parallel_branch_namespace(())  # Empty
    assert not is_parallel_branch_namespace(("execute:run_id", "123abc"))  # Not pure integer
