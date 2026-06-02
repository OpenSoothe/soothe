"""Tests for .env bootstrap before YAML config loading."""

from __future__ import annotations

import os

from soothe_daemon.bootstrap.env import load_dotenv_adjacent_to_yaml


def test_load_dotenv_adjacent_to_yaml_loads_sibling_env(tmp_path, monkeypatch) -> None:
    cfg_path = tmp_path / "config.yml"
    env_path = tmp_path / ".env"
    cfg_path.write_text("# yaml\n")
    env_path.write_text("BOOTSTRAP_ENV_TEST_FROM_ADJACENT=adjacent-value\n")
    monkeypatch.delenv("BOOTSTRAP_ENV_TEST_FROM_ADJACENT", raising=False)

    load_dotenv_adjacent_to_yaml(cfg_path)

    assert os.environ.get("BOOTSTRAP_ENV_TEST_FROM_ADJACENT") == "adjacent-value"
