"""Tests for CLI prompt option."""

from typer.testing import CliRunner

from soothe.ux.cli.main import app


def test_prompt_option_works() -> None:
    """Test that prompt can be passed via -p option."""
    runner = CliRunner()
    result = runner.invoke(app, ["-p", "test prompt"])
    assert result.exit_code == 0


def test_prompt_long_option_works() -> None:
    """Test that prompt can be passed via --prompt option."""
    runner = CliRunner()
    result = runner.invoke(app, ["--prompt", "test prompt"])
    assert result.exit_code == 0


def test_help_shows_prompt_option() -> None:
    """Test that help text shows the prompt option."""
    runner = CliRunner()
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "--prompt" in result.output
    assert "-p" in result.output
    # Check for prompt-related text (may be wrapped across lines)
    assert "Prompt" in result.output
    assert "headless" in result.output
