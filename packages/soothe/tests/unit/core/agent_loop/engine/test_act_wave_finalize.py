"""Tests for centralized Act-wave finalize resolution (IG-357)."""

from __future__ import annotations

from soothe.core.agent_loop.engine.act_wave_finalize import (
    compute_act_wave_finalize,
    provenance_is_task_delegate,
)


def test_compute_prefers_delegate_over_root_when_sequential() -> None:
    snap = compute_act_wave_finalize(
        parallel_multi_step=False,
        root_assistant_text="root ai",
        delegate_final_text="from task",
    )
    assert snap.visible_text == "from task"
    assert snap.provenance == "task_tool_aggregate"
    assert provenance_is_task_delegate(snap) is True


def test_compute_uses_root_when_no_delegate() -> None:
    snap = compute_act_wave_finalize(
        parallel_multi_step=False,
        root_assistant_text="  root ai \n",
        delegate_final_text=None,
    )
    assert snap.visible_text == "root ai"
    assert snap.provenance == "root_assistant_stream"
    assert provenance_is_task_delegate(snap) is False


def test_compute_parallel_multi_uses_merged_delegate_only() -> None:
    snap = compute_act_wave_finalize(
        parallel_multi_step=True,
        root_assistant_text="ignored",
        delegate_final_text="a\n\n---\n\nb",
    )
    assert snap.visible_text == "a\n\n---\n\nb"
    assert snap.provenance == "task_tool_aggregate"


def test_compute_parallel_multi_none_when_empty_delegate() -> None:
    snap = compute_act_wave_finalize(
        parallel_multi_step=True,
        root_assistant_text="root",
        delegate_final_text="",
    )
    assert snap.visible_text is None
    assert snap.provenance == "none"
