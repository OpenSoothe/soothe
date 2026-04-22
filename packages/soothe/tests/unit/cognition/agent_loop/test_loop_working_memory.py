"""Loop working memory (RFC-203)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from soothe.cognition.agent_loop import LoopWorkingMemory
from soothe.protocols.loop_working_memory import LoopWorkingMemoryProtocol


def test_render_empty() -> None:
    wm = LoopWorkingMemory(thread_id="t")
    assert wm.render_for_reason() == ""


def test_spill_large_output_to_soothe_home(tmp_path: Path) -> None:
    wm = LoopWorkingMemory(
        thread_id="thread-1",
        max_entry_chars_before_spill=20,
    )
    body = "line\n" * 50
    # Need to patch at module level where LoopWorkingMemory imports SOOTHE_HOME
    with patch("soothe.config.SOOTHE_HOME", str(tmp_path)):
        wm.record_step_result(
            step_id="s1",
            description="List files",
            output=body,
            error=None,
            success=True,
            workspace=str(tmp_path),
            thread_id="thread-1",
        )
    spill_dir = tmp_path / "data" / "threads" / "thread-1" / "working_memory"
    assert spill_dir.is_dir()
    files = list(spill_dir.rglob("step-s1-*.md"))
    assert len(files) == 1
    text = wm.render_for_reason()
    assert "read_file" in text
    assert "step-s1-" in text


def test_failed_step_recorded_inline() -> None:
    wm = LoopWorkingMemory(thread_id="t")
    wm.record_step_result(
        step_id="x",
        description="fail",
        output=None,
        error="boom",
        success=False,
        workspace=None,
        thread_id="t",
    )
    assert "✗" in wm.render_for_reason()
    assert "boom" in wm.render_for_reason()


def test_loop_working_memory_is_structural_protocol() -> None:
    wm = LoopWorkingMemory(thread_id="t")
    accept: LoopWorkingMemoryProtocol = wm
    assert accept is wm
