"""Unit tests for LoopRail catalog discovery and YAML loading."""

from __future__ import annotations

from pathlib import Path

import pytest

from soothe.rails import (
    LoopRailCatalog,
    RailCatalogError,
    get_builtin_rails_dir,
    get_rails_paths,
    load_rail_file,
)

EXPECTED_BUILTIN_IDS = frozenset(
    {
        "feature-dev",
        "bugfix",
        "maker-checker",
        "hotfix",
        "spike",
        "pr-review",
        "migration",
        "greenfield-system",
    }
)


def test_get_builtin_rails_dir_exists() -> None:
    path = get_builtin_rails_dir()
    assert path.is_dir()
    assert path.name == "builtin_rails"


def test_get_rails_paths_includes_builtins(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    home = tmp_path / "soothe_home"
    home.mkdir()
    monkeypatch.setattr("soothe.config.SOOTHE_HOME", home)
    # builtins.py imports SOOTHE_HOME inside the function from soothe.config
    monkeypatch.setattr("soothe.config.env.SOOTHE_HOME", home)

    paths = get_rails_paths()
    assert get_builtin_rails_dir() in paths
    assert (home / "rails") not in paths  # missing dir omitted

    (home / "rails").mkdir()
    paths = get_rails_paths()
    assert paths[0] == get_builtin_rails_dir()
    assert paths[1] == home / "rails"


def test_get_rails_paths_workspace_overrides(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "home"
    (home / "rails").mkdir(parents=True)
    ws = tmp_path / "ws"
    (ws / ".soothe" / "rails").mkdir(parents=True)
    monkeypatch.setattr("soothe.config.SOOTHE_HOME", home)
    monkeypatch.setattr("soothe.config.env.SOOTHE_HOME", home)

    paths = get_rails_paths(str(ws))
    assert paths[-1] == (ws / ".soothe" / "rails").resolve()


def test_builtin_catalog_loads_all_shipped_rails() -> None:
    catalog = LoopRailCatalog()
    ids = set(catalog.list_ids())
    assert EXPECTED_BUILTIN_IDS <= ids
    assert "default" not in ids

    for rail_id in EXPECTED_BUILTIN_IDS:
        rail = catalog.resolve(rail_id)
        assert rail.id == rail_id
        assert rail.version
        assert rail.summary
        assert rail.applies_when
        assert rail.flow or rail.rules
        assert rail.source_path is not None
        assert rail.source_path.stem == rail_id


def test_project_rail_overrides_builtin(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr("soothe.config.SOOTHE_HOME", home)
    monkeypatch.setattr("soothe.config.env.SOOTHE_HOME", home)

    ws = tmp_path / "ws"
    project_rails = ws / ".soothe" / "rails"
    project_rails.mkdir(parents=True)
    override = project_rails / "feature-dev.yml"
    override.write_text(
        """
id: feature-dev
version: "9.9"
summary: Project override of feature-dev.
applies_when: |
  Only when testing catalog precedence.
flow:
  - event: job_start
    then: review
""".strip()
        + "\n",
        encoding="utf-8",
    )

    catalog = LoopRailCatalog(workspace=str(ws))
    rail = catalog.resolve("feature-dev")
    assert rail.version == "9.9"
    assert rail.source_path == override.resolve()
    assert rail.flow[0]["then"] == "review"


def test_drafts_are_not_loaded(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    home = tmp_path / "home"
    rails = home / "rails"
    drafts = rails / "drafts"
    drafts.mkdir(parents=True)
    monkeypatch.setattr("soothe.config.SOOTHE_HOME", home)
    monkeypatch.setattr("soothe.config.env.SOOTHE_HOME", home)

    (drafts / "secret-draft.yml").write_text(
        """
id: secret-draft
version: "1.0"
summary: Should not load.
applies_when: never
flow:
  - event: job_start
    then: review
""".strip()
        + "\n",
        encoding="utf-8",
    )
    # Also place a non-draft sibling to ensure roots still work
    (rails / "ok.yml").write_text(
        """
id: ok
version: "1.0"
summary: Active rail.
applies_when: tests
flow:
  - event: job_start
    then: complete_job
""".strip()
        + "\n",
        encoding="utf-8",
    )

    catalog = LoopRailCatalog()
    assert "ok" in catalog.list_ids()
    assert "secret-draft" not in catalog.list_ids()


def test_load_rail_rejects_id_mismatch(tmp_path: Path) -> None:
    path = tmp_path / "feature-dev.yml"
    path.write_text(
        """
id: other-id
version: "1.0"
summary: Bad.
applies_when: x
flow:
  - event: job_start
    then: review
""".strip()
        + "\n",
        encoding="utf-8",
    )
    with pytest.raises(RailCatalogError, match="must match filename stem"):
        load_rail_file(path)


def test_load_rail_rejects_unknown_then(tmp_path: Path) -> None:
    path = tmp_path / "bad.yml"
    path.write_text(
        """
id: bad
version: "1.0"
summary: Bad then verb.
applies_when: x
flow:
  - event: job_start
    then: invent_custom_builtin
""".strip()
        + "\n",
        encoding="utf-8",
    )
    with pytest.raises(RailCatalogError, match="unknown then"):
        load_rail_file(path)


def test_load_rail_aliases_legacy_on_to_event(tmp_path: Path) -> None:
    """Legacy ``on:`` (YAML bool key or string) is normalized to ``event``."""
    path = tmp_path / "legacy.yml"
    # Intentionally unquoted on: — YAML 1.1 may parse the key as True
    path.write_text(
        "id: legacy\n"
        'version: "1.0"\n'
        "summary: Legacy on key.\n"
        "applies_when: test\n"
        "flow:\n"
        "  - on: job_start\n"
        "    then: review\n",
        encoding="utf-8",
    )
    rail = load_rail_file(path)
    assert rail.flow[0]["event"] == "job_start"
    assert "on" not in rail.flow[0]
    assert True not in rail.flow[0]


def test_resolve_missing_rail() -> None:
    catalog = LoopRailCatalog()
    with pytest.raises(RailCatalogError, match="rail not found"):
        catalog.resolve("does-not-exist-xyz")
