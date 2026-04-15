"""Unit tests for unified TUI history file behavior."""

from __future__ import annotations

import json

from soothe_cli.tui.widgets.history import HistoryManager


def _write_jsonl(path, rows: list[object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            if isinstance(row, str) and not row.startswith("{") and not row.startswith('"'):
                handle.write(row + "\n")
            else:
                handle.write(json.dumps(row) + "\n")


def test_history_manager_reads_unified_file_only(tmp_path) -> None:
    """History navigation should read from unified history.jsonl only."""
    base = tmp_path
    history_file = base / "history.jsonl"
    _write_jsonl(history_file, [{"text": "unified command", "index": 1}])

    manager = HistoryManager(history_file, max_entries=20)

    assert manager.get_previous("", query="") == "unified command"


def test_history_manager_does_not_read_legacy_input_history_file(tmp_path) -> None:
    """Legacy input_history.jsonl should not be read anymore."""
    base = tmp_path
    history_file = base / "history.jsonl"
    legacy_file = base / "input_history.jsonl"
    _write_jsonl(legacy_file, ["legacy command"])
    _write_jsonl(history_file, [{"text": "unified command", "index": 1}])

    manager = HistoryManager(history_file, max_entries=20)

    assert manager.get_previous("", query="") == "unified command"
    assert manager.get_previous("", query="") is None


def test_history_manager_writes_unified_dict_format(tmp_path) -> None:
    """Adding from TUI should write dict entries to history.jsonl."""
    base = tmp_path
    history_file = base / "history.jsonl"
    if history_file.exists():
        history_file.unlink()

    manager = HistoryManager(history_file, max_entries=20)
    manager.add("count README files")

    lines = history_file.read_text(encoding="utf-8").strip().splitlines()
    assert lines
    payload = json.loads(lines[-1])
    assert isinstance(payload, dict)
    assert payload.get("text") == "count README files"
    assert payload.get("thread_id") == "tui"
