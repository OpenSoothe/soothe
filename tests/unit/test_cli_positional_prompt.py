"""Tests for CLI positional prompt argument."""

from typer.testing import CliRunner

from soothe.ux.cli.main import app


def test_positional_prompt_works() -> None:
    """Test that prompt can be passed as positional argument."""
    runner = CliRunner()
    # This should work without errors (exit code 0)
    result = runner.invoke(app, ["test prompt"])
    assert result.exit_code == 0


def test_prompt_option_works() -> None:
    """Test that prompt can be passed via -p option."""
    runner = CliRunner()
    result = runner.invoke(app, ["-p", "test prompt"])
    assert result.exit_code == 0


def test_prompt_option_takes_precedence() -> None:
    """Test that -p option takes precedence over positional argument."""
    runner = CliRunner()
    # When -p is provided before positional, it should work
    result = runner.invoke(app, ["-p", "option value", "positional value"])
    assert result.exit_code == 0


def test_help_shows_positional_arg() -> None:
    """Test that help text shows the positional argument."""
    runner = CliRunner()
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "[PROMPT_ARG]" in result.output
    assert "Prompt to send as user message" in result.output
