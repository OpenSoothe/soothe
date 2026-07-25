"""Packaged setup templates must stay in sync with repo config/*.template.yml."""

from __future__ import annotations

from pathlib import Path

import pytest

from soothe_daemon.setup.paths import TEMPLATE_NAMES, monorepo_template_path, read_template_text


def _repo_root() -> Path:
    # tests/unit/setup/test_*.py → repo root
    return Path(__file__).resolve().parents[5]


@pytest.mark.parametrize("name", TEMPLATE_NAMES)
def test_packaged_template_matches_monorepo(name: str) -> None:
    repo = monorepo_template_path(name)
    if repo is None:
        pytest.skip("monorepo config/ templates not available")
    packaged = read_template_text(name)
    assert packaged == repo.read_text(encoding="utf-8")


@pytest.mark.parametrize("name", TEMPLATE_NAMES)
def test_repo_template_files_exist(name: str) -> None:
    stem = name.removesuffix(".yml")
    path = _repo_root() / "config" / f"{stem}.template.yml"
    assert path.is_file(), f"missing {path}"
