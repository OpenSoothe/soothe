"""Pure step-card activity module: row classification and stats (RFC-628)."""

from __future__ import annotations

from soothe_cli.tui.widgets.messages.cognition_step_activity import (
    StepRowClassifier,
    StepToolRow,
    count_distinct_tool_call_ids,
    has_task_activity_body,
    row_counts_for_main_tools,
    stats_title_suffix,
    task_delegation_dedupe_key,
)


def _row(
    tool_call_id: str,
    *,
    tool_name: str = "grep",
    is_task_row: bool = False,
    parent: str | None = None,
) -> StepToolRow:
    return StepToolRow(
        tool_call_id=tool_call_id,
        tool_name=tool_name,
        args={},
        phase="pending",
        parent_tool_call_id=parent,
        is_task_row=is_task_row,
    )


def test_classifier_splits_main_task_orphan_and_children() -> None:
    rows = [
        _row("ABC_01:s:grep:0"),
        _row(
            "ABC_01:s:task:0",
            tool_name="task",
            is_task_row=True,
        ),
        _row("ABC_01:t0:glob:1", tool_name="glob", parent="ABC_01:s:task:0"),
        _row("ABC_01:t1:ls:2", tool_name="ls"),
    ]
    index = StepRowClassifier.build("ABC-01", rows)
    assert len(index.main_tools) == 1
    assert index.main_tools[0].tool_call_id == "ABC_01:s:grep:0"
    assert len(index.task_delegations) == 1
    key = task_delegation_dedupe_key(index.task_delegations[0], "ABC-01")
    assert len(index.children_by_task[key]) == 1
    assert index.children_by_task[key][0].tool_call_id == "ABC_01:t0:glob:1"
    assert len(index.orphan_tools) == 1
    assert index.orphan_tools[0].tool_call_id == "ABC_01:t1:ls:2"


def test_stats_title_suffix_uses_total_tool_count() -> None:
    rows = [
        _row("ABC_01:s:grep:0"),
        _row("ABC_01:s:task:0", tool_name="task", is_task_row=True),
        _row("ABC_01:t0:glob:1", tool_name="glob", parent="ABC_01:s:task:0"),
    ]
    index = StepRowClassifier.build("ABC-01", rows)
    assert index.total_tool_count == 2
    assert index.task_delegation_count == 1
    assert stats_title_suffix(index) == " · 2 tools, 1 task"


def test_row_counts_for_main_tools_excludes_subgraph() -> None:
    main = _row("ABC_01:s:grep:0")
    subgraph = _row("ABC_01:t0:glob:0", tool_name="glob")
    assert row_counts_for_main_tools(main, "ABC-01") is True
    assert row_counts_for_main_tools(subgraph, "ABC-01") is False


def test_has_task_activity_body_from_main_tools_only() -> None:
    index = StepRowClassifier.build("ABC-01", [_row("ABC_01:s:grep:0")])
    assert has_task_activity_body(index, [], {}) is True


def test_count_distinct_tool_call_ids_dedupes() -> None:
    rows = [_row("ABC_01:s:grep:0"), _row("ABC_01:s:grep:0")]
    assert count_distinct_tool_call_ids(rows) == 1
