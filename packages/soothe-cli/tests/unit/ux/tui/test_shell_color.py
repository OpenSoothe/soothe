"""Tests for TUI shell color helpers."""

from __future__ import annotations

import os

from soothe_cli.tui.shell_color import shell_subprocess_env, wrap_shell_command_for_color


def test_shell_subprocess_env_sets_color_defaults() -> None:
    env = shell_subprocess_env({"PATH": "/bin", "TERM": "dumb"})
    assert env["PATH"] == "/bin"
    assert env["TERM"] == "dumb"
    assert env["FORCE_COLOR"] == "1"
    assert env["CLICOLOR_FORCE"] == "1"
    assert env["COLORTERM"] == "truecolor"


def test_shell_subprocess_env_fills_missing_term() -> None:
    env = shell_subprocess_env({"PATH": os.environ.get("PATH", "/bin")})
    assert env["TERM"] == "xterm-256color"


def test_wrap_shell_command_for_color_prefixes_exports_and_git_wrapper() -> None:
    wrapped = wrap_shell_command_for_color("git diff")
    assert wrapped.endswith("git diff")
    assert "FORCE_COLOR=1" in wrapped
    assert 'git() { command git -c color.ui=always "$@"; }' in wrapped


def test_wrap_shell_command_for_color_empty_command() -> None:
    assert wrap_shell_command_for_color("   ") == ""
