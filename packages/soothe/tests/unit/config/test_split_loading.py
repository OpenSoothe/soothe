"""Tests for split-file SootheConfig loading."""

from __future__ import annotations

from pathlib import Path

import pytest

from soothe.config import SootheConfig


def test_from_split_yaml_files_merges_nano_and_soothe(tmp_path: Path) -> None:
    nano_path = tmp_path / "nano.yml"
    soothe_path = tmp_path / "soothe.yml"

    nano_path.write_text(
        "providers:\n"
        "  - name: openai\n"
        "    provider_type: openai\n"
        "    api_key: test-key\n"
        "agent:\n"
        "  runtime:\n"
        "    recursion_limit: 321\n",
        encoding="utf-8",
    )
    soothe_path.write_text(
        "agent:\n  loop:\n    max_iterations: 77\ncron:\n  max_jobs: 25\n",
        encoding="utf-8",
    )

    cfg = SootheConfig.from_split_yaml_files(
        nano_path=str(nano_path),
        soothe_path=str(soothe_path),
    )
    assert cfg.providers[0].name == "openai"
    assert cfg.agent.runtime.recursion_limit == 321
    assert cfg.agent.loop.max_iterations == 77
    assert cfg.cron.max_jobs == 25


def test_from_split_yaml_files_requires_soothe_overlay(tmp_path: Path) -> None:
    nano_path = tmp_path / "nano.yml"
    nano_path.write_text("agent:\n  runtime:\n    recursion_limit: 222\n", encoding="utf-8")

    with pytest.raises(TypeError):
        SootheConfig.from_split_yaml_files(nano_path=str(nano_path))  # type: ignore[call-arg]


def test_from_split_yaml_files_rejects_wrong_soothe_keys(tmp_path: Path) -> None:
    nano_path = tmp_path / "nano.yml"
    soothe_path = tmp_path / "soothe.yml"

    nano_path.write_text(
        "agent:\n  runtime:\n    recursion_limit: 200\n",
        encoding="utf-8",
    )
    soothe_path.write_text(
        "providers:\n  - name: openai\n    provider_type: openai\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="Config ownership violation"):
        SootheConfig.from_split_yaml_files(
            nano_path=str(nano_path),
            soothe_path=str(soothe_path),
        )
