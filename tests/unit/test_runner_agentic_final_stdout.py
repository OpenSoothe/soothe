"""Unit tests for agentic final stdout shaping (IG-119 / test-case1)."""

from __future__ import annotations

from soothe.core.runner._runner_agentic import _agentic_final_stdout_text


def test_prefers_user_summary_over_full_output() -> None:
    assert (
        _agentic_final_stdout_text(
            user_summary="Found 12 project READMEs.",
            full_output="['/a/README.md']noise",
        )
        == "Found 12 project READMEs."
    )


def test_strips_leading_list_repr_from_full_output() -> None:
    out = _agentic_final_stdout_text(
        user_summary="",
        full_output="['/x/README.md', '/y/README.md']Found **68** files.\n\nDetails below.",
    )
    assert out is not None
    assert out.startswith("Found **68**")
    assert "/x/README" not in out


def test_strips_nested_or_repeated_list_prefixes() -> None:
    blob = "['/a']" + "['/b']" + "Final answer."
    assert _agentic_final_stdout_text(user_summary="", full_output=blob) == "Final answer."


def test_returns_none_for_empty() -> None:
    assert _agentic_final_stdout_text(user_summary="", full_output=None) is None
    assert _agentic_final_stdout_text(user_summary="   ", full_output="") is None


def test_returns_none_when_only_list_blob_without_trailing_prose() -> None:
    """Strip loop consumes everything — runner should fall back to evidence_summary."""
    assert _agentic_final_stdout_text(user_summary="", full_output="['/a/x.md', '/b/y.md']") is None
