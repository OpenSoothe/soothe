"""Unit tests for skill-card description truncation behavior."""

from soothe_cli.tui.widgets.messages import _build_skill_description_preview


def test_description_preview_not_truncated_when_short() -> None:
    """Short descriptions should render as-is in collapsed state."""
    preview, truncated = _build_skill_description_preview(
        "Short description",
        max_lines=4,
        max_chars=300,
        ellipsis="…",
    )
    assert preview == "Short description"
    assert not truncated


def test_description_preview_truncates_long_single_line() -> None:
    """Long single-line descriptions should collapse with an ellipsis."""
    preview, truncated = _build_skill_description_preview(
        "x" * 400,
        max_lines=4,
        max_chars=120,
        ellipsis="…",
    )
    assert truncated
    assert len(preview) <= 121
    assert preview.endswith("…")


def test_description_preview_truncates_by_line_budget() -> None:
    """Descriptions exceeding preview lines should be collapsed."""
    description = "\n".join(f"line-{i}" for i in range(8))
    preview, truncated = _build_skill_description_preview(
        description,
        max_lines=3,
        max_chars=300,
        ellipsis="…",
    )
    assert truncated
    assert preview.splitlines() == ["line-0", "line-1", "line-2…"]
