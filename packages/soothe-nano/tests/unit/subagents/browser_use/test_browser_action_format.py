"""Tests for browser_use action formatting."""

from __future__ import annotations

from soothe_nano.subagents.browser_use.action_format import summarize_browser_step_action


def test_summarize_navigate_action_model_dump() -> None:
    action = [
        {
            "root": {
                "navigate": {"url": "https://www.moji.com/Weather?city=Zhoushan"},
            }
        }
    ]
    tool, preview = summarize_browser_step_action(action)
    assert tool == "Navigate"
    assert "moji.com" in preview


def test_summarize_wait_action() -> None:
    action = [{"root": {"wait": {"seconds": 3}}}]
    tool, preview = summarize_browser_step_action(action)
    assert tool == "Wait"
    assert preview == "3s"


def test_summarize_fallback_raw_string() -> None:
    tool, preview = summarize_browser_step_action("unknown blob")
    assert tool == "Step"
    assert "unknown" in preview
