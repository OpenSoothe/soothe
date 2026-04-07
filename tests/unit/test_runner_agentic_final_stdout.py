"""Unit tests for agentic final stdout shaping (IG-119 / IG-123)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from soothe.core.runner._runner_agentic import (
    _AGENTIC_REPORT_FULL_DISPLAY_MAX,
    _AGENTIC_REPORT_PREVIEW_MAX,
    _agentic_final_stdout_text,
)


def _mock_config(*, sandboxed: bool = True) -> MagicMock:
    cfg = MagicMock()
    cfg.security.allow_paths_outside_workspace = not sandboxed
    return cfg


def test_prefers_normalized_body_under_threshold_over_user_summary() -> None:
    body = "Full architecture report here." * 10  # well under 5000
    assert (
        _agentic_final_stdout_text(
            user_summary="Short headline only.",
            full_output=body,
            thread_id="tid",
            workspace="/tmp",
            config=_mock_config(),
        )
        == body
    )


def test_strips_leading_list_repr_then_prefers_body() -> None:
    out = _agentic_final_stdout_text(
        user_summary="Ignored when body exists.",
        full_output="['/x/README.md', '/y/README.md']Found **68** files.\n\nDetails below.",
        thread_id="tid",
        workspace="/tmp",
        config=_mock_config(),
    )
    assert out is not None
    assert out.startswith("Found **68**")
    assert "/x/README" not in out


def test_strips_nested_or_repeated_list_prefixes() -> None:
    blob = "['/a']" + "['/b']" + "Final answer."
    assert (
        _agentic_final_stdout_text(
            user_summary="",
            full_output=blob,
            thread_id="tid",
            workspace="/tmp",
            config=_mock_config(),
        )
        == "Final answer."
    )


def test_user_summary_when_normalized_body_empty() -> None:
    assert (
        _agentic_final_stdout_text(
            user_summary="Found 12 project READMEs.",
            full_output="['/a/README.md', '/b/y.md']",
            thread_id="tid",
            workspace="/tmp",
            config=_mock_config(),
        )
        == "Found 12 project READMEs."
    )


def test_returns_none_for_empty() -> None:
    assert (
        _agentic_final_stdout_text(
            user_summary="",
            full_output=None,
            thread_id="tid",
            workspace="/tmp",
            config=_mock_config(),
        )
        is None
    )
    assert (
        _agentic_final_stdout_text(
            user_summary="   ",
            full_output="",
            thread_id="tid",
            workspace="/tmp",
            config=_mock_config(),
        )
        is None
    )


def test_returns_none_when_only_list_blob_without_trailing_prose() -> None:
    """Strip loop consumes everything — runner should fall back to evidence_summary."""
    assert (
        _agentic_final_stdout_text(
            user_summary="",
            full_output="['/a/x.md', '/b/y.md']",
            thread_id="tid",
            workspace="/tmp",
            config=_mock_config(),
        )
        is None
    )


def test_exact_threshold_prints_full_without_spool() -> None:
    body = "x" * _AGENTIC_REPORT_FULL_DISPLAY_MAX
    out = _agentic_final_stdout_text(
        user_summary="summary",
        full_output=body,
        thread_id="tid",
        workspace="/tmp",
        config=_mock_config(),
    )
    assert out == body
    assert len(out) == _AGENTIC_REPORT_FULL_DISPLAY_MAX


def test_over_threshold_spools_and_announces_path(tmp_path: Path) -> None:
    root = tmp_path
    body = "y" * (_AGENTIC_REPORT_FULL_DISPLAY_MAX + 50)
    with patch("soothe.config.SOOTHE_HOME", str(root)):
        out = _agentic_final_stdout_text(
            user_summary="summary",
            full_output=body,
            thread_id="thread-a",
            workspace=str(root),
            config=_mock_config(sandboxed=True),
        )
    assert out is not None
    assert out.startswith("y" * _AGENTIC_REPORT_PREVIEW_MAX)
    assert "..." in out
    assert "Full report:" in out
    run_dir = root / "runs" / "thread-a"
    saved = list(run_dir.glob("final_report_*.md"))
    assert len(saved) == 1
    assert saved[0].read_text(encoding="utf-8") == body
    assert str(saved[0].resolve()) in out


def test_over_threshold_without_workspace_skips_write_but_truncates() -> None:
    body = "z" * (_AGENTIC_REPORT_FULL_DISPLAY_MAX + 10)
    out = _agentic_final_stdout_text(
        user_summary="",
        full_output=body,
        thread_id="tid",
        workspace=None,
        config=_mock_config(),
    )
    assert out is not None
    assert "file not written" in out
    assert "final_report_*.md" in out
    assert out.startswith("z" * _AGENTIC_REPORT_PREVIEW_MAX)
    assert "..." in out
