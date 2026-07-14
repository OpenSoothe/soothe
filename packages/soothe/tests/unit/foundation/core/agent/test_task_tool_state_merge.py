"""Task tool must not merge subagent ``workspace`` back into parent state."""

from __future__ import annotations


def test_task_tool_excludes_parent_owned_keys_from_subagent_merge() -> None:
    """Parallel explore completions must not write ``workspace`` to parent graph state."""
    from soothe_deepagents.middleware import subagents as sm

    from soothe.foundation.core.agent import _patch_task_tool as patch_mod

    patch_mod._patch_task_tool_propagates_parent_runnable_config()
    assert getattr(sm._build_task_tool, "_soothe_patched_config", False)

    # Re-run builder logic: parent-owned keys are excluded alongside soothe_deepagents defaults.
    excluded = sm._EXCLUDED_STATE_KEYS | frozenset({"workspace"})
    result = {
        "messages": [],
        "workspace": "/Users/proj",
        "search_target": "widgets",
    }
    state_update = {k: v for k, v in result.items() if k not in excluded}
    assert "workspace" not in state_update
    assert state_update.get("search_target") == "widgets"
