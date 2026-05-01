"""CLI Task subgraph labeling (IG-334)."""

from __future__ import annotations

from pytest import CaptureFixture

from soothe_cli.cli.renderer import CliRenderer


def test_tool_call_with_task_scope_prefixes_stderr(capsys: CaptureFixture[str]) -> None:
    r = CliRenderer()
    r.on_tool_call(
        "glob",
        {"glob_pattern": "**/README*"},
        "",
        is_main=False,
        task_scope=("functions.task:0", "explore"),
    )
    err = capsys.readouterr().err.splitlines()
    assert any("⚙ [Task(explore):#0]" in line for line in err)


def test_assistant_text_with_task_scope_writes_stdout(capsys: CaptureFixture[str]) -> None:
    r = CliRenderer()
    r.on_assistant_text(
        "Found one readme.",
        is_main=False,
        is_streaming=False,
        task_scope=("tid", "explore"),
    )
    out = capsys.readouterr().out
    assert "[Task(explore):tid]" in out  # opaque short id kept as-is
    assert "Found one readme." in out


def test_tool_join_line_includes_task_scope_once(capsys: CaptureFixture[str]) -> None:
    r = CliRenderer()
    r.on_tool_call(
        "list_files",
        {"path": "/"},
        "join-me",
        is_main=False,
        task_scope=("functions.task:2", "explore"),
    )
    r.on_tool_result(
        "list_files",
        "Found 1 item",
        "join-me",
        is_error=False,
        is_main=False,
        task_scope=("functions.task:2", "explore"),
    )
    line = next(l for l in capsys.readouterr().err.splitlines() if "->" in l)
    assert "⚙ [Task(explore):#2]" in line
    assert "ListFiles" in line or "list_files" in line.lower()
