"""Task delegation tree under step cards (SubAgentName(desc) + nested tool stats)."""

from __future__ import annotations

from soothe_cli.tui.widgets.messages import CognitionStepMessage


def _plain(content: object) -> str:
    return str(content)


def test_task_activity_tree_shows_name_desc_and_child_stats() -> None:
    card = CognitionStepMessage("ABC-01", "Scan workspace", id="stp-task-tree")
    card.add_tool_call(
        "ABC_01:s:task:0",
        "task",
        {"subagent_type": "explore", "description": "scan the repository"},
        is_task_row=True,
    )
    card.add_tool_call(
        "ABC_01:t0:grep:0",
        "grep",
        {"pattern": "x"},
        parent_tool_call_id="ABC_01:s:task:0",
    )
    card.add_tool_call(
        "ABC_01:t0:grep:1",
        "grep",
        {"pattern": "y"},
        parent_tool_call_id="ABC_01:s:task:0",
    )
    card.add_tool_call(
        "ABC_01:t0:glob:0",
        "glob",
        {"pattern": "**/*"},
        parent_tool_call_id="ABC_01:s:task:0",
    )

    text = _plain(card._step_task_activity_content())
    assert "Explore(scan the repository)" in text
    assert "Grep(2)" in text
    assert "Glob(1)" in text
    assert "○ ○" not in text


def test_task_activity_links_children_by_unified_task_index() -> None:
    card = CognitionStepMessage("YKF-01", "Delegate", id="stp-task-idx")
    card.add_tool_call(
        "YKF_01:s:task:0",
        "task",
        {"subagent_type": "research", "description": "find docs"},
        is_task_row=True,
    )
    card.add_tool_call("YKF_01:t0:read_file:1", "read_file", {"path": "a.md"})

    text = _plain(card._step_task_activity_content())
    assert "Research(find docs)" in text
    assert "ReadFile(1)" in text


def test_append_subagent_activity_attaches_to_task_branch() -> None:
    card = CognitionStepMessage("ABC-01", "Scan", id="stp-task-note")
    card.add_tool_call(
        "ABC_01:s:task:0",
        "task",
        {"subagent_type": "explore", "description": "scan"},
        is_task_row=True,
    )
    card.append_subagent_activity("Found 3 modules", task_tool_call_id="ABC_01:s:task:0")

    text = _plain(card._step_task_activity_content())
    assert "Explore(scan)" in text
    assert "Found 3 modules" in text


def test_step_compose_places_status_after_task_activity() -> None:
    card = CognitionStepMessage("ABC-01", "Scan", id="stp-order")
    widget_ids = [getattr(w, "id", None) for w in card.compose()]
    assert widget_ids.index("step-cognition-status") > widget_ids.index(
        "step-cognition-subagent-notes"
    )
    assert widget_ids.index("step-cognition-status") > widget_ids.index("step-cognition-detail")


def test_task_branch_child_line_shows_stats_and_running_status() -> None:
    card = CognitionStepMessage("ABC-01", "Scan", id="stp-phase")
    card.add_tool_call(
        "ABC_01:s:task:0",
        "task",
        {"subagent_type": "explore", "description": "scan"},
        is_task_row=True,
    )
    card.add_tool_call(
        "ABC_01:t0:grep:0",
        "grep",
        {"pattern": "x"},
        parent_tool_call_id="ABC_01:s:task:0",
    )
    card.set_tool_running("ABC_01:t0:grep:0")
    text = _plain(card._step_task_activity_content())
    assert "Grep(1) · running" in text


def test_duplicate_task_rows_dedupe_to_one_branch() -> None:
    card = CognitionStepMessage("JIY-01", "Explore root", id="stp-dedupe")
    card.add_tool_call(
        "JIY_01:s:task:0",
        "task",
        {"subagent_type": "explore", "description": "scan repo"},
        is_task_row=True,
    )
    card.add_tool_call(
        "call_provider_task_0",
        "task",
        {"subagent_type": "explore", "description": "scan repo"},
        is_task_row=True,
    )
    rows = card._iter_task_delegation_rows()
    assert len(rows) == 1
    text = _plain(card._step_task_activity_content())
    assert text.count("Explore(scan repo)") == 1


def test_child_stats_link_via_normalized_parent_id() -> None:
    card = CognitionStepMessage("JIY-01", "Explore", id="stp-parent-norm")
    card.add_tool_call(
        "JIY_01:s:task:0",
        "task",
        {"subagent_type": "explore", "description": "scan"},
        is_task_row=True,
    )
    card.add_tool_call(
        "JIY_01:t0:glob:0",
        "glob",
        {"pattern": "**/*"},
        parent_tool_call_id="JIY_01:s:task:0",
    )
    text = _plain(card._step_task_activity_content())
    assert "Glob(1)" in text


def test_status_line_still_excludes_nested_task_tools() -> None:
    card = CognitionStepMessage("ABC-01", "Scan", id="stp-task-status")
    card.add_tool_call("ABC_01:s:grep:0", "grep", {})
    card.add_tool_call(
        "ABC_01:s:task:0",
        "task",
        {"subagent_type": "explore", "description": "scan"},
        is_task_row=True,
    )
    card.add_tool_call(
        "ABC_01:t0:glob:0",
        "glob",
        {},
        parent_tool_call_id="ABC_01:s:task:0",
    )
    suffix = card._stats_title_suffix()
    assert "Grep(1)" in suffix
    assert "Glob" not in suffix
