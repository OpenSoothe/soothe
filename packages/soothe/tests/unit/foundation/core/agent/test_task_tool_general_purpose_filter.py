"""Tests for general-purpose subagent filtering in the patched task tool."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from soothe.foundation.core.agent import _patch_task_tool as patch_mod


@pytest.fixture(autouse=True)
def _ensure_task_tool_patch() -> None:
    patch_mod.apply_task_tool_patch()


def _sample_subagents() -> list[dict[str, object]]:
    deep_research_runnable = MagicMock()
    gp_runnable = MagicMock()
    return [
        {
            "name": "deep_research",
            "description": "Research and evidence gathering",
            "runnable": deep_research_runnable,
        },
        {
            "name": patch_mod.GENERAL_PURPOSE_SUBAGENT_NAME,
            "description": "General-purpose agent with all tools",
            "runnable": gp_runnable,
        },
    ]


def test_build_task_tool_hides_general_purpose_when_disabled() -> None:
    from deepagents.middleware import subagents as sm

    with patch_mod.general_purpose_subagent_build_context(False):
        tool = sm._build_task_tool(_sample_subagents())

    assert patch_mod.GENERAL_PURPOSE_SUBAGENT_NAME not in tool.description
    assert "deep_research" in tool.description
    assert "general-purpose agent is provided" not in tool.description


def test_build_task_tool_includes_general_purpose_when_enabled() -> None:
    from deepagents.middleware import subagents as sm

    with patch_mod.general_purpose_subagent_build_context(True):
        tool = sm._build_task_tool(_sample_subagents())

    assert patch_mod.GENERAL_PURPOSE_SUBAGENT_NAME in tool.description
    assert "deep_research" in tool.description


def test_filter_general_purpose_subagents() -> None:
    specs = _sample_subagents()
    filtered = patch_mod._filter_general_purpose_subagents(specs)
    assert len(filtered) == 1
    assert filtered[0]["name"] == "deep_research"


def test_task_tool_description_template_strips_general_purpose_section() -> None:
    base = (
        "Intro\n{available_agents}\n"
        "7. When only the general-purpose agent is provided, use it.\n"
        "### Example usage with custom agents:\n"
        "Tail"
    )
    trimmed = patch_mod._task_tool_description_template(base, include_general_purpose=False)
    assert "general-purpose agent is provided" not in trimmed
    assert "### Example usage with custom agents:" in trimmed
    assert "Intro" in trimmed
