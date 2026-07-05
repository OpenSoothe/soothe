"""Welcome banner layout: compact metadata row under the title art."""

from __future__ import annotations

from pathlib import Path


def test_welcome_banner_source_does_not_show_workspace_or_version_in_art() -> None:
    source = Path(__file__).resolve().parents[4] / "src/soothe_cli/tui/widgets/welcome.py"
    text = source.read_text(encoding="utf-8")
    assert "Source:" not in text
    assert "workspace_path" not in text
    assert "resolve_source_display_path" not in text


def test_banner_art_strings_no_longer_embed_version() -> None:
    config_source = (
        Path(__file__).resolve().parents[4] / "src/soothe_cli/tui/config.py"
    ).read_text(encoding="utf-8")
    assert "v{__version__}" not in config_source.split("def get_banner")[0]
