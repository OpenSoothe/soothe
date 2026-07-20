"""Tests for ModelCallProfiler system prompt block breakdown."""

from __future__ import annotations

from soothe_nano.middleware.model_call_profiler import _block_char_sizes


def test_block_char_sizes_counts_agent_instructions() -> None:
    text = (
        "base prompt\n"
        "<AGENT_INSTRUCTIONS>\nlong body\n</AGENT_INSTRUCTIONS>\n"
        "<AVAILABLE_TOOLS>\n- t1\n</AVAILABLE_TOOLS>"
    )
    sizes = _block_char_sizes(text)
    assert sizes["agent_instructions"] > 0
    assert sizes["available_tools"] > 0
    assert sizes["base"] >= 0
