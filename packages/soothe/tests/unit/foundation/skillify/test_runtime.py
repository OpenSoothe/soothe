"""Tests for Skillify service warehouse path resolution."""

from __future__ import annotations

from pathlib import Path

import soothe_nano

from soothe.foundation.skillify.service import _default_warehouse_paths, resolve_warehouse_paths

_BUILTIN_SKILLS = Path(soothe_nano.__file__).resolve().parent / "skills" / "builtin_skills"


def test_default_warehouse_paths_include_user_skill_dirs(tmp_path: Path) -> None:
    soothe_home = tmp_path / ".soothe"
    defaults = _default_warehouse_paths(soothe_home)
    assert defaults == [
        str(Path.home() / ".agents" / "skills"),
        str(_BUILTIN_SKILLS),
        str(soothe_home / "skills"),
    ]


def test_resolve_warehouse_paths_prepends_defaults(tmp_path: Path) -> None:
    soothe_home = tmp_path / ".soothe"
    resolved = resolve_warehouse_paths(soothe_home, [])
    assert resolved == _default_warehouse_paths(soothe_home)


def test_resolve_warehouse_paths_keeps_custom_paths(tmp_path: Path) -> None:
    soothe_home = tmp_path / ".soothe"
    custom = "/tmp/extra-skills"
    resolved = resolve_warehouse_paths(soothe_home, [custom])
    assert resolved[0] == str(Path.home() / ".agents" / "skills")
    assert resolved[1].endswith("/skills/builtin_skills")
    assert resolved[2] == str(soothe_home / "skills")
    assert resolved[3] == custom


def test_resolve_warehouse_paths_dedupes_configured_defaults(tmp_path: Path) -> None:
    soothe_home = tmp_path / ".soothe"
    agents = str(Path.home() / ".agents" / "skills")
    resolved = resolve_warehouse_paths(soothe_home, [agents, "/tmp/more"])
    assert resolved.count(agents) == 1
    assert resolved[-1] == "/tmp/more"
