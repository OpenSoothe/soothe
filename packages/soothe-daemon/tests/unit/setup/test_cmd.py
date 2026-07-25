"""Tests for ``soothed setup`` orchestration and CLI wiring."""

from __future__ import annotations

import re
from io import StringIO
from pathlib import Path

from typer.testing import CliRunner

from soothe_daemon.cli import app
from soothe_daemon.setup.cmd import run_setup
from soothe_daemon.setup.paths import config_paths

runner = CliRunner()
_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


def _strip_ansi(text: str) -> str:
    return _ANSI_RE.sub("", text)


def test_run_setup_yes_scaffolds(tmp_path: Path) -> None:
    out = StringIO()
    err = StringIO()
    code = run_setup(
        config_dir=tmp_path,
        yes=True,
        skip_doctor=True,
        stdout=out,
        stderr=err,
        stdin=StringIO(""),
    )
    assert code == 0
    paths = config_paths(tmp_path)
    assert paths["nano"].is_file()
    assert paths["soothe"].is_file()
    assert paths["daemon"].is_file()
    assert "Setup complete" in out.getvalue()


def test_run_setup_skip_provider(tmp_path: Path) -> None:
    code = run_setup(
        config_dir=tmp_path,
        skip_provider=True,
        skip_doctor=True,
        stdout=StringIO(),
        stderr=StringIO(),
        stdin=StringIO(""),
    )
    assert code == 0
    assert (tmp_path / "nano.yml").is_file()


def test_cli_setup_yes(tmp_path: Path) -> None:
    result = runner.invoke(
        app,
        ["setup", "--config-dir", str(tmp_path), "--yes", "--skip-doctor"],
    )
    assert result.exit_code == 0, result.stdout + result.stderr
    assert (tmp_path / "nano.yml").is_file()
    assert (tmp_path / "daemon.yml").is_file()
    assert "Setup complete" in result.stdout


def test_cli_setup_help() -> None:
    result = runner.invoke(app, ["setup", "--help"])
    assert result.exit_code == 0
    help_text = _strip_ansi(result.stdout)
    assert "--yes" in help_text
    assert "--config-dir" in help_text
