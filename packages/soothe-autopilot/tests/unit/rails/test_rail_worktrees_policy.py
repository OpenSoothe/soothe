"""Tests for the rail-declared ``worktrees:`` lifecycle policy.

Verifies that a rail YAML ``worktrees:`` section is parsed into
``RailDefinition.worktrees``, bound into ``RailJobState`` at bind time, and
that the recycle-on-merge / recycle-on-complete gates honor the policy.
"""

from __future__ import annotations

from pathlib import Path

from soothe_autopilot.rails.builtins_exec import RailJobState
from soothe_autopilot.rails.catalog import _normalize_worktrees, load_rail_file


def _write_rail(tmp_path: Path, body: str) -> Path:
    p = tmp_path / "test-rail.yml"
    p.write_text(body, encoding="utf-8")
    return p


_BASE_RAIL = """\
id: test-rail
version: "1.0"
summary: Test rail for worktree policy.
applies_when: test
flow:
  - event: job_start
    then: complete_job
"""


def test_normalize_worktrees_defaults_when_absent() -> None:
    assert _normalize_worktrees(None, path=Path("x.yml")) == {}


def test_normalize_worktrees_full() -> None:
    out = _normalize_worktrees(
        {"enabled": False, "recycle_on_merge": False, "recycle_on_complete": False},
        path=Path("x.yml"),
    )
    assert out == {
        "enabled": False,
        "recycle_on_merge": False,
        "recycle_on_complete": False,
    }


def test_normalize_worktrees_rejects_unknown_key() -> None:
    try:
        _normalize_worktrees({"bogus": True}, path=Path("x.yml"))
        raise AssertionError("expected RailCatalogError")
    except Exception as exc:
        assert "unknown key" in str(exc)


def test_normalize_worktrees_rejects_non_bool() -> None:
    try:
        _normalize_worktrees({"enabled": "yes"}, path=Path("x.yml"))
        raise AssertionError("expected RailCatalogError")
    except Exception as exc:
        assert "must be a bool" in str(exc)


def test_rail_definition_has_empty_worktrees_when_absent(tmp_path: Path) -> None:
    p = _write_rail(tmp_path, _BASE_RAIL)
    rail = load_rail_file(p)
    assert rail.worktrees == {}


def test_rail_definition_parses_worktrees_section(tmp_path: Path) -> None:
    body = _BASE_RAIL.replace(
        "applies_when: test\n",
        "applies_when: test\n"
        "worktrees:\n"
        "  enabled: false\n"
        "  recycle_on_merge: false\n"
        "  recycle_on_complete: false\n",
    )
    p = _write_rail(tmp_path, body)
    rail = load_rail_file(p)
    assert rail.worktrees == {
        "enabled": False,
        "recycle_on_merge": False,
        "recycle_on_complete": False,
    }


def test_rail_definition_parses_partial_worktrees_section(tmp_path: Path) -> None:
    body = _BASE_RAIL.replace(
        "applies_when: test\n",
        "applies_when: test\nworktrees:\n  recycle_on_merge: false\n",
    )
    p = _write_rail(tmp_path, body)
    rail = load_rail_file(p)
    assert rail.worktrees == {"recycle_on_merge": False}


def test_railjobstate_defaults_recycle_true() -> None:
    """Default state recycles on merge and complete (safe default)."""
    state = RailJobState(job_id="j1", rail_id="test-rail", rail_version="1.0")
    assert state.worktrees_enabled is True
    assert state.worktree_recycle_on_merge is True
    assert state.worktree_recycle_on_complete is True


def test_railjobstate_back_compat_missing_keys_default_true() -> None:
    """Old persisted state without recycle keys loads with safe defaults."""
    raw = {
        "job_id": "j1",
        "rail_id": "test-rail",
        "rail_version": "1.0",
        "worktrees_enabled": True,
        # worktree_recycle_on_merge / _on_complete absent (old state)
    }
    state = RailJobState(
        job_id=raw["job_id"],
        rail_id=raw["rail_id"],
        rail_version=raw["rail_version"],
        worktrees_enabled=bool(raw.get("worktrees_enabled", True)),
        worktree_recycle_on_merge=bool(raw.get("worktree_recycle_on_merge", True)),
        worktree_recycle_on_complete=bool(raw.get("worktree_recycle_on_complete", True)),
    )
    assert state.worktree_recycle_on_merge is True
    assert state.worktree_recycle_on_complete is True
