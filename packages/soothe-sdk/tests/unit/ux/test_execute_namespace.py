"""Tests for execute stream namespace classification."""

from __future__ import annotations

from soothe_sdk.ux.execute_namespace import (
    is_execute_namespace_key,
    is_root_execute_namespace_key,
    is_step_level_execute_namespace_key,
)


def test_is_execute_namespace_key() -> None:
    assert is_execute_namespace_key(("execute:abc",))
    assert is_execute_namespace_key(("execute:abc/1",))
    assert not is_execute_namespace_key(())
    assert not is_execute_namespace_key(("execute:abc", "tools:xyz"))
    assert not is_execute_namespace_key(("tools:xyz",))


def test_is_root_execute_namespace_key() -> None:
    assert is_root_execute_namespace_key(("execute:abc",))
    assert not is_root_execute_namespace_key(("execute:abc/1",))
    assert not is_root_execute_namespace_key(("execute:abc", "tools:xyz"))


def test_is_step_level_execute_namespace_key() -> None:
    assert is_step_level_execute_namespace_key(("execute:abc",))
    assert is_step_level_execute_namespace_key(("execute:abc/1",))
    assert not is_step_level_execute_namespace_key(("tools:sub",))
