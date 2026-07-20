"""Regression: library dependency check must return True when satisfied."""

from __future__ import annotations

import pytest

from soothe_nano.plugin.loader import PluginLoader
from soothe_nano.plugin.registry import PluginRegistry


def test_check_library_dependency_true_when_version_satisfies_specifier() -> None:
    """Satisfied PEP 440 constraints must be truthy (not implicit None)."""
    loader = PluginLoader(PluginRegistry())
    pytest.importorskip("langgraph", reason="langgraph not installed")
    assert loader._check_library_dependency("langgraph>=0.2.0") is True
