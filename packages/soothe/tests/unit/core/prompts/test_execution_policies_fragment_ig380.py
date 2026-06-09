"""Execution policies fragment includes IG-380 discovery guidance."""

from soothe.foundation.loop.prompts.fragments import EXECUTION_POLICIES_FRAGMENT


def test_execution_policies_includes_filesystem_discovery_ig380() -> None:
    assert "Discovery" in EXECUTION_POLICIES_FRAGMENT
    assert "glob" in EXECUTION_POLICIES_FRAGMENT
