"""Tests for CLI prompt option."""

from typer.testing import CliRunner

from soothe_cli.cli.main import app


def test_prompt_option_works(monkeypatch) -> None:
    """Test that prompt can be passed via -p option."""
    # Mock the implementation to prevent actually running the agent
    captured = {}
    monkeypatch.setattr("soothe_cli.shared.load_config", lambda _config: None)
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
    monkeypatch.setattr("soothe_cli.shared.load_config", lambda _config: None)
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
    assert "Prompt" in result.output
    assert "headless" in result.output
