"""Task delegation tree under step cards (SubAgentName(desc) + nested tool stats)."""

from __future__ import annotations

from soothe_cli.tui.widgets.messages import CognitionStepMessage


def _plain(content: object) -> str:
    return str(content)


def test_no_blank_line_between_task_branch_and_main_step_tools() -> None:
    """Main-graph tools (e.g. ListFiles) must sit directly under the task branch."""
    card = CognitionStepMessage("PGY-01", "Scan Frontend and Backend", id="stp-no-gap")
    card.add_tool_call(
        "PGY_01:s:task:0",
        "task",
        {"subagent_type": "explore", "description": "scan both trees"},
        is_task_row=True,
    )
    card.add_tool_call(
        "PGY_01:s:list_files:0",
        "list_files",
        {"path": "~/Workspace/Longan"},
    )
    text = _plain(card._step_task_activity_content())
    assert "Explore(scan both trees)" in text
    assert "ListFiles" in text
    lines = [ln for ln in text.split("\n") if ln.strip()]
    list_idx = next(i for i, ln in enumerate(lines) if "ListFiles" in ln)
    assert list_idx > 0
    assert "scan both" in lines[list_idx - 1]


def test_task_delegation_label_collapses_multiline_description() -> None:
    card = CognitionStepMessage("MLN-01", "Scan", id="stp-task-multiline-desc")
    card.add_tool_call(
        "MLN_01:s:task:0",
        "task",
        {
            "subagent_type": "explore",
            "description": "Line one\nLine two\n  Line three",
        },
        is_task_row=True,
    )
    text = _plain(card._step_task_activity_content())
    assert "Explore(Line one Line two Line three)" in text
    assert "\n" not in text.split("Explore(", 1)[-1].split(")", 1)[0]


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
        {"subagent_type": "tacitus", "description": "find docs"},
        is_task_row=True,
    )
    card.add_tool_call("YKF_01:t0:read_file:1", "read_file", {"path": "a.md"})

    text = _plain(card._step_task_activity_content())
    assert "Tacitus(find docs)" in text
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
    text = _plain(card._step_task_activity_content())
    assert "Grep(x)" in text
    assert text.index("Grep(x)") < text.index("Running...")
    assert "· Grep(1)" in text


def test_task_branch_child_line_with_empty_args_has_no_empty_parentheses() -> None:
    card = CognitionStepMessage("ABC-01", "Scan", id="stp-empty-args")
    card.add_tool_call(
        "ABC_01:s:task:0",
        "task",
        {"subagent_type": "explore", "description": "scan"},
        is_task_row=True,
    )
    card.add_tool_call(
        "ABC_01:t0:read_file:0",
        "read_file",
        {},
        parent_tool_call_id="ABC_01:s:task:0",
    )
    text = _plain(card._step_task_activity_content())
    assert "ReadFile" in text
    assert "ReadFile()" not in text


def test_task_branch_parses_raw_args_when_structured_args_are_empty() -> None:
    card = CognitionStepMessage("ABC-01", "Scan", id="stp-raw-args")
    card.add_tool_call(
        "ABC_01:s:task:0",
        "task",
        {"subagent_type": "explore", "description": "scan"},
        is_task_row=True,
    )
    card.add_tool_call(
        "ABC_01:t0:grep:0",
        "grep",
        {},
        raw_args='{"pattern":"x"}',
        parent_tool_call_id="ABC_01:s:task:0",
    )
    text = _plain(card._step_task_activity_content())
    assert "Grep(x)" in text


def test_task_branch_late_explicit_args_override_stale_raw_placeholder() -> None:
    card = CognitionStepMessage("ABC-01", "Scan", id="stp-stale-raw")
    card.add_tool_call(
        "ABC_01:s:task:0",
        "task",
        {"subagent_type": "explore", "description": "scan"},
        is_task_row=True,
    )
    card.add_tool_call(
        "ABC_01:t0:list_files:0",
        "list_files",
        {"_subgraph_tool": True},
        raw_args='{"_subgraph_tool":true}',
        parent_tool_call_id="ABC_01:s:task:0",
    )
    card.update_tool_args("ABC_01:t0:list_files:0", {"path": "/Users/tester/project"})
    text = _plain(card._step_task_activity_content())
    assert "ListFiles(" in text
    assert "project" in text


def test_pending_step_shows_branch_pending_without_task_rows() -> None:
    card = CognitionStepMessage("WAA-02", "Blocked step", id="stp-wait")
    # After IG-422 refactor, pending status is handled by _status_widget, not _step_task_activity_content.
    # Without task delegation rows, _step_task_activity_content returns empty Content.
    text = _plain(card._step_task_activity_content())
    assert text == ""  # No task rows → empty task activity content
    assert not card._has_task_activity_body()  # No subagent activity scheduled


def test_pending_step_with_task_delegation_shows_child_pending() -> None:
    card = CognitionStepMessage("WAA-03", "Future explore", id="stp-wait-task")
    card.add_tool_call(
        "WAA_03:s:task:0",
        "task",
        {"subagent_type": "explore", "description": "scan later"},
        is_task_row=True,
    )
    # Tool arrival can promote internal state; keep plan-style pending for the branch UI.
    card._status = "pending"
    card._deferred_running = False
    text = _plain(card._step_task_activity_content())
    assert "Explore(scan later)" in text
    assert "Pending..." in text


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


def test_subgraph_task_level_id_does_not_overwrite_main_delegation() -> None:
    """Regression: ``FHG_01:t0:task:0`` must not replace ``FHG_01:s:task:0`` args."""
    card = CognitionStepMessage("FHG-01", "Explore soothe-sdk", id="stp-overwrite")
    card.add_tool_call(
        "FHG_01:s:task:0",
        "task",
        {"subagent_type": "explore", "description": "Explore soothe-sdk package"},
        is_task_row=True,
    )
    card.add_tool_call(
        "FHG_01:t0:task:0",
        "task",
        {"description": "Check soothe-cli dependencies", "subagent_type": "explore"},
        parent_tool_call_id="FHG_01:s:task:0",
    )
    rows = card._iter_task_delegation_rows()
    assert len(rows) == 1
    assert "soothe-sdk" in str(rows[0].args.get("description", ""))
    text = _plain(card._step_task_activity_content())
    assert "Explore(Explore soothe-sdk package)" in text
    assert "Check soothe-cli" not in text


def test_task_branch_hides_redundant_opaque_task_metadata_row() -> None:
    card = CognitionStepMessage("FHG-01", "Explore soothe-sdk", id="stp-hide-opaque-task")
    card.add_tool_call(
        "FHG_01:s:task:0",
        "task",
        {"subagent_type": "explore", "description": "Count all file types"},
        is_task_row=True,
    )
    card.add_tool_call(
        "tool-49EA56F8116423E97FF19695B55Cca1",
        "tool-49EA56F8116423E97FF19695B55Cca1",
        {
            "subagent_type": "explore",
            "description": "Count all file types",
        },
        parent_tool_call_id="FHG_01:s:task:0",
    )
    text = _plain(card._step_task_activity_content())
    assert "Explore(Count all file types)" in text
    assert "Tool-49" not in text


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


def test_successful_step_marks_unfinished_task_tools_done() -> None:
    """Regression: completed steps must not show Skipped/Pending on task branches."""
    card = CognitionStepMessage("ABC-01", "Explore codebase", id="stp-done-task")
    card.add_tool_call(
        "ABC_01:s:task:0",
        "task",
        {"subagent_type": "explore", "description": "find files"},
        is_task_row=True,
    )
    card.add_tool_call(
        "ABC_01:t0:read_file:0",
        "read_file",
        {"path": "a.py"},
        parent_tool_call_id="ABC_01:s:task:0",
    )
    card.add_tool_call(
        "ABC_01:t0:grep:1",
        "grep",
        {"pattern": "deepxiv"},
        parent_tool_call_id="ABC_01:s:task:0",
    )
    card.set_running()
    card.set_complete(True, 83_000, 23, "Done")

    text = _plain(card._step_task_activity_content())
    assert "Skipped" not in text
    assert "Pending" not in text
    assert "Done" in text
    assert "ReadFile(1)" in text


def test_failed_step_still_marks_unfinished_task_tools_skipped() -> None:
    card = CognitionStepMessage("ABC-02", "Broken explore", id="stp-fail-task")
    card.add_tool_call(
        "ABC_02:s:task:0",
        "task",
        {"subagent_type": "explore", "description": "scan"},
        is_task_row=True,
    )
    card.add_tool_call(
        "ABC_02:t0:glob:0",
        "glob",
        {"pattern": "**/*"},
        parent_tool_call_id="ABC_02:s:task:0",
    )
    card.set_running()
    card.set_complete(False, 1000, 1, "failed")
    card.mark_unfinished_tools_on_step_complete(success=False)

    text = _plain(card._step_task_activity_content())
    assert "Skipped" in text


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


def test_task_branch_shows_latest_three_child_tools_above_running() -> None:
    card = CognitionStepMessage("ABC-01", "Scan", id="stp-child-preview")
    card.add_tool_call(
        "ABC_01:s:task:0",
        "task",
        {"subagent_type": "explore", "description": "scan"},
        is_task_row=True,
    )
    for i in range(7):
        card.add_tool_call(
            f"ABC_01:t0:grep:{i}",
            "grep",
            {"pattern": f"p{i}"},
            parent_tool_call_id="ABC_01:s:task:0",
        )
    card.set_running()
    text = _plain(card._step_task_activity_content())
    assert "Grep(p4)" in text
    assert "Grep(p5)" in text
    assert "Grep(p6)" in text
    assert "Grep(p0)" not in text
    assert "Grep(p1)" not in text
    assert "Grep(p2)" not in text
    assert "Grep(p3)" not in text
    assert text.index("Grep(p6)") < text.index("Running...")


def test_step_first_level_shows_latest_three_main_tools() -> None:
    card = CognitionStepMessage("ABC-01", "Scan only", id="stp-main-preview")
    for i in range(7):
        card.add_tool_call(f"ABC_01:s:grep:{i}", "grep", {"pattern": f"m{i}"})
    assert card._has_task_activity_body()
    text = _plain(card._step_task_activity_content())
    assert not text.startswith("\n")
    assert "Grep(m4)" in text
    assert "Grep(m5)" in text
    assert "Grep(m6)" in text
    assert "Grep(m0)" not in text
    assert "Grep(m1)" not in text
    assert "Grep(m2)" not in text
    assert "Grep(m3)" not in text


def test_orphan_subgraph_tool_rows_still_render_on_step_card() -> None:
    card = CognitionStepMessage("ABC-01", "Scan only", id="stp-orphan-subgraph")
    # No visible task delegation row, but subgraph tool row arrived.
    card.add_tool_call(
        "ABC_01:t0:ls:0",
        "ls",
        {"path": "."},
        parent_tool_call_id="ABC_01:s:task:0",
    )

    assert card._has_task_activity_body()
    text = _plain(card._step_task_activity_content())
    assert "ListFiles(.)" in text


def test_combined_task_and_main_tools() -> None:
    card = CognitionStepMessage("ABC-01", "Mixed", id="stp-mixed-preview")
    card.add_tool_call(
        "ABC_01:s:task:0",
        "task",
        {"subagent_type": "explore", "description": "scan repo"},
        is_task_row=True,
    )
    for i in range(6):
        card.add_tool_call(
            f"ABC_01:t0:glob:{i}",
            "glob",
            {"pattern": f"t{i}"},
            parent_tool_call_id="ABC_01:s:task:0",
        )
    for i in range(6):
        card.add_tool_call(f"ABC_01:s:read_file:{i}", "read_file", {"file_path": f"/a{i}.py"})
    card.set_running()
    text = _plain(card._step_task_activity_content())
    assert "Explore(scan repo)" in text
    assert "Glob(t5)" in text
    assert "Glob(t0)" not in text
    assert "ReadFile" in text
    assert text.index("Explore(scan repo)") < text.index("ReadFile")
    assert "Glob(1)" in text or "Glob(6)" in text or "Glob(5)" in text
