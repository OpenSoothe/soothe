"""Tests for SDK formatting utilities."""

from __future__ import annotations

from pathlib import Path

from soothe_sdk.utils.formatting import convert_and_abbreviate_path


def test_convert_and_abbreviate_path_home_child_uses_tilde_slash(monkeypatch) -> None:
    """Home descendants must render as ``~/...`` (not ``~foo``)."""
    fake_home = Path("/Users/tester")
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: fake_home))

    rendered = convert_and_abbreviate_path("/Users/tester/Workspace/project")

    assert rendered == "~/Workspace/project"


def test_convert_and_abbreviate_path_home_root_uses_plain_tilde(monkeypatch) -> None:
    """Home root should render as ``~``."""
    fake_home = Path("/Users/tester")
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: fake_home))

    rendered = convert_and_abbreviate_path("/Users/tester")

    assert rendered == "~"
