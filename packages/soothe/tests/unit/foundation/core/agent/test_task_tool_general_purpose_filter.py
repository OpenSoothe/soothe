"""Tests for upstream task tool general-purpose handling."""

from __future__ import annotations

from unittest.mock import MagicMock


def _sample_subagents(include_general_purpose: bool) -> list[dict[str, object]]:
    deep_research_runnable = MagicMock()
    specs: list[dict[str, object]] = [
        {
            "name": "deep_research",
            "description": "Research and evidence gathering",
            "runnable": deep_research_runnable,
        }
    ]
    if include_general_purpose:
        gp_runnable = MagicMock()
        specs.append(
            {
                "name": "general-purpose",
                "description": "General-purpose agent with all tools",
                "runnable": gp_runnable,
            }
        )
    return specs


def test_build_task_tool_hides_general_purpose_guidance_when_absent() -> None:
    from soothe_deepagents.middleware import subagents as sm

    tool = sm._build_task_tool(_sample_subagents(include_general_purpose=False))
    assert "deep_research" in tool.description


def test_build_task_tool_includes_general_purpose_guidance_when_present() -> None:
    from soothe_deepagents.middleware import subagents as sm

    tool = sm._build_task_tool(_sample_subagents(include_general_purpose=True))
    assert "general-purpose" in tool.description
    assert "deep_research" in tool.description
