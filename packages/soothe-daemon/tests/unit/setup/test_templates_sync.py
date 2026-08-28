"""Monorepo config/templates/ symlinks resolve to the packaged templates."""

from __future__ import annotations

from pathlib import Path

import pytest

from soothe_daemon.setup.paths import TEMPLATE_NAMES, monorepo_template_path, read_template_text


def _repo_root() -> Path:
    # tests/unit/setup/test_*.py → repo root
    return Path(__file__).resolve().parents[5]


@pytest.mark.parametrize("name", TEMPLATE_NAMES)
def test_repo_template_symlinks_exist(name: str) -> None:
    """config/templates/<name> is a symlink (or file) present in the checkout."""
    path = _repo_root() / "config" / "templates" / name
    assert path.is_file(), f"missing {path}"


@pytest.mark.parametrize("name", TEMPLATE_NAMES)
def test_monorepo_template_matches_packaged(name: str) -> None:
    """The config/templates/ symlink resolves to the same content as the packaged template."""
    repo = monorepo_template_path(name)
    if repo is None:
        pytest.skip("config/templates/ not available")
    packaged = read_template_text(name)
    assert packaged == repo.read_text(encoding="utf-8")
