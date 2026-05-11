"""Tests for CLI prompt option."""

from unittest.mock import MagicMock

import pytest
from typer.testing import CliRunner

from soothe_cli.cli.main import app


def test_prompt_option_works(monkeypatch) -> None:
    """Test that prompt can be passed via -p option."""
    # Mock the implementation to prevent actually running the agent
    captured = {}
    monkeypatch.setattr("soothe_cli.shared.load_config", lambda _config=None: None)
    monkeypatch.setattr("soothe_cli.shared.setup_logging", lambda _cfg: None)
    monkeypatch.setattr(
        "soothe_cli.cli.commands.run_cmd.run_impl",
        lambda **kwargs: captured.update(kwargs),
    )

    runner = CliRunner()
    result = runner.invoke(app, ["-p", "test prompt"])
    assert result.exit_code == 0
    assert captured.get("prompt") == "test prompt"


def test_prompt_long_option_works(monkeypatch) -> None:
    """Test that prompt can be passed via --prompt option."""
    # Mock the implementation to prevent actually running the agent
    captured = {}
    monkeypatch.setattr("soothe_cli.shared.load_config", lambda _config=None: None)
    monkeypatch.setattr("soothe_cli.shared.setup_logging", lambda _cfg: None)
    monkeypatch.setattr(
        "soothe_cli.cli.commands.run_cmd.run_impl",
        lambda **kwargs: captured.update(kwargs),
    )

    runner = CliRunner()
    result = runner.invoke(app, ["--prompt", "test prompt"])
    assert result.exit_code == 0
    assert captured.get("prompt") == "test prompt"


def test_help_shows_prompt_option() -> None:
    """Test that help text shows the prompt option."""
    runner = CliRunner()
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    # Typer may show --prompt or -prompt depending on terminal width
    # In narrow terminals (like GitHub CI), it shows -prompt (abbreviated)
    # In wider terminals, it shows --prompt (full)
    assert "--prompt" in result.output or "-prompt" in result.output
    assert "-p" in result.output
    # Check for prompt-related text (may be wrapped across lines)
    assert "--prompt" in result.output or "-p" in result.output
    out_low = result.output.lower()
    assert "prompt" in out_low
    assert "headless" in out_low


def _minimal_cfg() -> MagicMock:
    cfg = MagicMock()
    cfg.logging_level = None
    return cfg


def test_prompt_defaults_to_headless_run_impl(monkeypatch: pytest.MonkeyPatch) -> None:
    """Non-empty -p should select headless unless resuming a loop or --tui."""
    monkeypatch.setattr("soothe_cli.cli.commands.run_cmd.load_config", lambda _config=None: _minimal_cfg())
    monkeypatch.setattr("soothe_cli.cli.commands.run_cmd.setup_logging", lambda *_a, **_k: None)
    mode: dict[str, str] = {}

    def _headless(_cfg, _prompt: str, **_kwargs) -> None:
        mode["which"] = "headless"

    def _tui(_cfg, **_kwargs) -> None:
        mode["which"] = "tui"

    monkeypatch.setattr("soothe_cli.cli.commands.run_cmd.run_headless", _headless)
    monkeypatch.setattr("soothe_cli.cli.commands.run_cmd.run_tui", _tui)

    from soothe_cli.cli.commands import run_cmd

    run_cmd.run_impl(
        prompt="hello",
        resume_loop_id=None,
        no_tui=False,
        autonomous=False,
        max_iterations=None,
        tui_with_prompt=False,
    )
    assert mode.get("which") == "headless"


def test_prompt_with_resume_loop_uses_tui(monkeypatch: pytest.MonkeyPatch) -> None:
    """Loop continue passes resume_loop_id — keep TUI even with a prompt."""
    monkeypatch.setattr("soothe_cli.cli.commands.run_cmd.load_config", lambda _config=None: _minimal_cfg())
    monkeypatch.setattr("soothe_cli.cli.commands.run_cmd.setup_logging", lambda *_a, **_k: None)
    mode: dict[str, str] = {}

    def _headless(*_a, **_k) -> None:
        mode["which"] = "headless"

    def _tui(*_a, **_k) -> None:
        mode["which"] = "tui"

    monkeypatch.setattr("soothe_cli.cli.commands.run_cmd.run_headless", _headless)
    monkeypatch.setattr("soothe_cli.cli.commands.run_cmd.run_tui", _tui)

    from soothe_cli.cli.commands import run_cmd

    run_cmd.run_impl(
        prompt="hello",
        resume_loop_id="loop_abc",
        no_tui=False,
        autonomous=False,
        max_iterations=None,
        tui_with_prompt=False,
    )
    assert mode.get("which") == "tui"


def test_prompt_with_tui_flag_uses_tui(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("soothe_cli.cli.commands.run_cmd.load_config", lambda _config=None: _minimal_cfg())
    monkeypatch.setattr("soothe_cli.cli.commands.run_cmd.setup_logging", lambda *_a, **_k: None)
    mode: dict[str, str] = {}

    def _headless(*_a, **_k) -> None:
        mode["which"] = "headless"

    def _tui(*_a, **_k) -> None:
        mode["which"] = "tui"

    monkeypatch.setattr("soothe_cli.cli.commands.run_cmd.run_headless", _headless)
    monkeypatch.setattr("soothe_cli.cli.commands.run_cmd.run_tui", _tui)

    from soothe_cli.cli.commands import run_cmd

    run_cmd.run_impl(
        prompt="hello",
        resume_loop_id=None,
        no_tui=False,
        autonomous=False,
        max_iterations=None,
        tui_with_prompt=True,
    )
    assert mode.get("which") == "tui"


def test_no_tui_without_prompt_exits(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("soothe_cli.cli.commands.run_cmd.load_config", lambda _config=None: _minimal_cfg())
    monkeypatch.setattr("soothe_cli.cli.commands.run_cmd.setup_logging", lambda *_a, **_k: None)
    monkeypatch.setattr("soothe_cli.cli.commands.run_cmd.run_headless", lambda *_a, **_k: None)
    monkeypatch.setattr("soothe_cli.cli.commands.run_cmd.run_tui", lambda *_a, **_k: None)

    from soothe_cli.cli.commands import run_cmd

    with pytest.raises(SystemExit) as exc:
        run_cmd.run_impl(
            prompt=None,
            resume_loop_id=None,
            no_tui=True,
            autonomous=False,
            max_iterations=None,
        )
    assert exc.value.code == 1
