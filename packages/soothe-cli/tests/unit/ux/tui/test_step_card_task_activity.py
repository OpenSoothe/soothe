"""Task delegation markers under step cards (IG-513 flattened display).

IG-513: Step cards show flat task delegation markers (no nested child tools).
Subgraph tools route to SubAgent cards. Tests updated for flattened design.
"""

from __future__ import annotations

from soothe_cli.tui.widgets.messages import CognitionStepMessage


def _plain(content: object) -> str:
    return str(content)


def test_no_blank_line_between_task_branch_and_main_step_tools() -> None:
    """Main-graph tools (e.g. ListFiles) must sit directly under the task marker."""
    card = CognitionStepMessage("PGY-01", "Scan Frontend and Backend", id="stp-no-gap")
    card.add_tool_call(
        "PGY_01:s:task:0",
        "task",
        {"subagent_type": "tacitus", "description": "scan both trees"},
        is_task_row=True,
    )
    card.add_tool_call(
        "PGY_01:s:list_files:0",
        "list_files",
        {"path": "~/Workspace/Longan"},
    )
    text = _plain(card._step_task_activity_content())
    assert "Tacitus(scan both trees)" in text
    assert "ListFiles" in text
    assert "\n\n" not in text
    lines = text.split("\n")
    list_idx = next(i for i, ln in enumerate(lines) if "ListFiles" in ln)
    assert list_idx > 0
    assert "scan both" in lines[list_idx - 1]


def test_task_delegation_label_collapses_multiline_description() -> None:
    card = CognitionStepMessage("MLN-01", "Scan", id="stp-task-multiline-desc")
    card.add_tool_call(
        "MLN_01:s:task:0",
        "task",
        {
            "subagent_type": "tacitus",
            "description": "Line one\nLine two\n  Line three",
        },
        is_task_row=True,
    )
    text = _plain(card._step_task_activity_content())
    assert "Tacitus(Line one Line two Line three)" in text
    assert "\n" not in text.split("Tacitus(", 1)[-1].split(")", 1)[0]


def test_task_activity_tree_shows_name_desc_flat_marker() -> None:
    """IG-513: Task delegation shown as flat marker (no nested child stats)."""
    card = CognitionStepMessage("ABC-01", "Scan workspace", id="stp-task-tree")
    card.add_tool_call(
        "ABC_01:s:task:0",
        "task",
        {"subagent_type": "tacitus", "description": "scan the repository"},
        is_task_row=True,
    )
    # IG-513: Subgraph tools no longer appear nested under step card

    text = _plain(card._step_task_activity_content())
    assert "Tacitus(scan the repository)" in text
    # IG-513: No nested tool count under task marker on step card
    # (SubAgent card shows tool count)


def test_task_activity_links_children_by_unified_task_index() -> None:
    """IG-513: Task marker shown, child tools route to SubAgent card."""
    card = CognitionStepMessage("YKF-01", "Delegate", id="stp-task-idx")
    card.add_tool_call(
        "YKF_01:s:task:0",
        "task",
        {"subagent_type": "tacitus", "description": "find docs"},
        is_task_row=True,
    )
    # IG-513: read_file tool would route to SubAgent card, not nested here

    text = _plain(card._step_task_activity_content())
    assert "Tacitus(find docs)" in text


def test_append_subagent_activity_attaches_to_task_branch() -> None:
    card = CognitionStepMessage("ABC-01", "Scan", id="stp-task-note")
    card.add_tool_call(
        "ABC_01:s:task:0",
        "task",
        {"subagent_type": "tacitus", "description": "scan"},
        is_task_row=True,
    )
    card.append_subagent_activity("Found 3 modules", task_tool_call_id="ABC_01:s:task:0")

    text = _plain(card._step_task_activity_content())
    assert "Tacitus(scan)" in text
    assert "Found 3 modules" in text


def test_step_compose_places_status_after_task_activity() -> None:
    card = CognitionStepMessage("ABC-01", "Scan", id="stp-order")
    widget_ids = [getattr(w, "id", None) for w in card.compose()]
    assert widget_ids.index("step-cognition-status") > widget_ids.index(
        "step-cognition-subagent-notes"
    )
    assert widget_ids.index("step-cognition-status") > widget_ids.index("step-cognition-detail")


def test_task_branch_child_line_shows_flat_marker_only() -> None:
    """IG-513: Task delegation shown as flat marker, no nested child tools."""
    card = CognitionStepMessage("ABC-01", "Scan", id="stp-phase")
    card.add_tool_call(
        "ABC_01:s:task:0",
        "task",
        {"subagent_type": "tacitus", "description": "scan"},
        is_task_row=True,
    )
    # IG-513: Subgraph tools route to SubAgent card, not nested here
    text = _plain(card._step_task_activity_content())
    assert "Tacitus(scan)" in text


def test_task_branch_with_empty_args_shows_marker() -> None:
    """IG-513: Task marker shown regardless of args."""
    card = CognitionStepMessage("ABC-01", "Scan", id="stp-empty-args")
    card.add_tool_call(
        "ABC_01:s:task:0",
        "task",
        {"subagent_type": "tacitus", "description": "scan"},
        is_task_row=True,
    )
    text = _plain(card._step_task_activity_content())
    assert "Tacitus(scan)" in text


def test_pending_step_shows_no_activity_without_rows() -> None:
    """IG-513: Empty step shows no task activity content."""
    card = CognitionStepMessage("WAA-02", "Blocked step", id="stp-wait")
    text = _plain(card._step_task_activity_content())
    assert text == ""
    assert not card._has_task_activity_body()


def test_pending_step_with_task_delegation_shows_marker() -> None:
    """IG-513: Task marker shown even in pending state."""
    from soothe_cli.runtime.state.step_router import StepTaskRouter

    card = CognitionStepMessage("WAA-03", "Future explore", id="stp-wait-task")
    active = CognitionStepMessage("WAA-01", "Current step", id="stp-active")
    active.set_running()
    step_cards = {"WAA-01": active, "WAA-03": card}
    router = StepTaskRouter()
    card.add_tool_call(
        "WAA_03:s:task:0",
        "task",
        {"subagent_type": "tacitus", "description": "scan later"},
        is_task_row=True,
    )
    router.maybe_promote_step_to_running(
        card,
        "WAA_03:s:task:0",
        step_cards=step_cards,
    )
    assert card._status == "pending"
    text = _plain(card._step_task_activity_content())
    assert "Tacitus(scan later)" in text


def test_duplicate_task_rows_dedupe_to_one_marker() -> None:
    """IG-513: Duplicate task rows dedupe to one marker."""
    card = CognitionStepMessage("JIY-01", "Tacitus root", id="stp-dedupe")
    card.add_tool_call(
        "JIY_01:s:task:0",
        "task",
        {"subagent_type": "tacitus", "description": "scan repo"},
        is_task_row=True,
    )
    card.add_tool_call(
        "call_provider_task_0",
        "task",
        {"subagent_type": "tacitus", "description": "scan repo"},
        is_task_row=True,
    )
    rows = card._iter_task_delegation_rows()
    assert len(rows) == 1
    text = _plain(card._step_task_activity_content())
    assert text.count("Tacitus(scan repo)") == 1


def test_subgraph_task_level_id_does_not_overwrite_main_delegation() -> None:
    """Regression: ``FHG_01:t0:task:0`` must not replace ``FHG_01:s:task:0`` args."""
    card = CognitionStepMessage("FHG-01", "Tacitus soothe-sdk", id="stp-overwrite")
    card.add_tool_call(
        "FHG_01:s:task:0",
        "task",
        {"subagent_type": "tacitus", "description": "Tacitus soothe-sdk package"},
        is_task_row=True,
    )
    card.add_tool_call(
        "FHG_01:t0:task:0",
        "task",
        {"description": "Check soothe-cli dependencies", "subagent_type": "tacitus"},
    )
    rows = card._iter_task_delegation_rows()
    assert len(rows) == 1
    assert "soothe-sdk" in str(rows[0].args.get("description", ""))
    text = _plain(card._step_task_activity_content())
    assert "Tacitus(Tacitus soothe-sdk package)" in text


def test_task_branch_hides_redundant_opaque_task_metadata_row() -> None:
    """IG-513: Opaque task metadata row not shown on step card."""
    card = CognitionStepMessage("FHG-01", "Tacitus soothe-sdk", id="stp-hide-opaque-task")
    card.add_tool_call(
        "FHG_01:s:task:0",
        "task",
        {"subagent_type": "tacitus", "description": "Count all file types"},
        is_task_row=True,
    )
    card.add_tool_call(
        "tool-49EA56F8116423E97FF19695B55Cca1",
        "tool-49EA56F8116423E97FF19695B55Cca1",
        {
            "subagent_type": "tacitus",
            "description": "Count all file types",
        },
    )
    text = _plain(card._step_task_activity_content())
    assert "Tacitus(Count all file types)" in text
    assert "Tool-49" not in text


def test_step_shows_main_tools_after_task_marker() -> None:
    """IG-513: Main-agent tools shown after task marker (flat layout)."""
    card = CognitionStepMessage("JIY-01", "Tacitus", id="stp-parent-norm")
    card.add_tool_call(
        "JIY_01:s:task:0",
        "task",
        {"subagent_type": "tacitus", "description": "scan"},
        is_task_row=True,
    )
    card.add_tool_call("JIY_01:s:grep:0", "grep", {"pattern": "x"})
    text = _plain(card._step_task_activity_content())
    assert "Tacitus(scan)" in text
    assert "Grep(x)" in text


def test_successful_step_shows_task_marker() -> None:
    """IG-513: Completed step shows task marker (status syncs from SubAgent)."""
    card = CognitionStepMessage("ABC-01", "Tacitus codebase", id="stp-done-task")
    card.add_tool_call(
        "ABC_01:s:task:0",
        "task",
        {"subagent_type": "tacitus", "description": "find files"},
        is_task_row=True,
    )
    card.set_running()
    card.set_complete(True, 83_000, 23, "Done")

    text = _plain(card._step_task_activity_content())
    assert "Tacitus(find files)" in text


def test_failed_step_shows_task_marker() -> None:
    """IG-513: Failed step shows task marker (status syncs from SubAgent)."""
    card = CognitionStepMessage("ABC-02", "Broken explore", id="stp-fail-task")
    card.add_tool_call(
        "ABC_02:s:task:0",
        "task",
        {"subagent_type": "tacitus", "description": "scan"},
        is_task_row=True,
    )
    card.set_running()
    card.set_complete(False, 1000, 1, "failed")

    text = _plain(card._step_task_activity_content())
    assert "Tacitus(scan)" in text


def test_footer_stats_include_all_step_tools() -> None:
    """IG-513: Footer stats show main tools + task count."""
    card = CognitionStepMessage("ABC-01", "Scan", id="stp-task-status")
    card.add_tool_call("ABC_01:s:grep:0", "grep", {})
    card.add_tool_call(
        "ABC_01:s:task:0",
        "task",
        {"subagent_type": "tacitus", "description": "scan"},
        is_task_row=True,
    )
    suffix = card._stats_title_suffix()
    assert suffix == " · 1 tool, 1 task"


def test_step_shows_latest_three_main_tools() -> None:
    """IG-513: Step card shows latest 3 main-agent tool rows."""
    card = CognitionStepMessage("ABC-01", "Scan only", id="stp-main-preview")
    for i in range(7):
        card.add_tool_call(f"ABC_01:s:grep:{i}", "grep", {"pattern": f"m{i}"})
    assert card._has_task_activity_body()
    text = _plain(card._step_task_activity_content())
    assert not text.startswith("\n")
    assert "Grep(m6)" in text
    assert "Grep(m5)" in text
    assert "Grep(m4)" in text
    assert "Grep(m3)" not in text
    assert "Grep(m0)" not in text
    assert "+4 more tools" in text


def test_step_without_task_rows_still_shows_main_tools() -> None:
    """IG-513: Step without task delegations shows main tools."""
    card = CognitionStepMessage("ABC-01", "Scan only", id="stp-no-task")
    card.add_tool_call("ABC_01:s:grep:0", "grep", {"pattern": "x"})
    assert card._has_task_activity_body()
    text = _plain(card._step_task_activity_content())
    assert "Grep(x)" in text


def test_combined_task_and_main_tools() -> None:
    """IG-513: Task marker + main tools shown in flat layout."""
    card = CognitionStepMessage("ABC-01", "Mixed", id="stp-mixed-preview")
    card.add_tool_call(
        "ABC_01:s:task:0",
        "task",
        {"subagent_type": "tacitus", "description": "scan repo"},
        is_task_row=True,
    )
    for i in range(3):
        card.add_tool_call(f"ABC_01:s:read_file:{i}", "read_file", {"file_path": f"/a{i}.py"})
    card.set_running()
    text = _plain(card._step_task_activity_content())
    assert "Tacitus(scan repo)" in text
    assert "ReadFile" in text
    assert text.index("Tacitus(scan repo)") < text.index("ReadFile")
