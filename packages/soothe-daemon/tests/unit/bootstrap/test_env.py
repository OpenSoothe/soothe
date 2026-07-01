"""Tests for .env bootstrap before YAML config loading."""

from __future__ import annotations

import os

from soothe_daemon.bootstrap.env import bootstrap_dotenv, load_dotenv_adjacent_to_yaml


def test_load_dotenv_adjacent_to_yaml_loads_sibling_env(tmp_path, monkeypatch) -> None:
    cfg_path = tmp_path / "config.yml"
    env_path = tmp_path / ".env"
    cfg_path.write_text("# yaml\n")
    env_path.write_text("BOOTSTRAP_ENV_TEST_FROM_ADJACENT=adjacent-value\n")
    monkeypatch.delenv("BOOTSTRAP_ENV_TEST_FROM_ADJACENT", raising=False)

    load_dotenv_adjacent_to_yaml(cfg_path)

    assert os.environ.get("BOOTSTRAP_ENV_TEST_FROM_ADJACENT") == "adjacent-value"


def test_bootstrap_dotenv_walks_up_to_parent_env(tmp_path, monkeypatch) -> None:
    project_root = tmp_path / "project"
    nested = project_root / "packages" / "app"
    nested.mkdir(parents=True)
    (project_root / ".env").write_text("BOOTSTRAP_ENV_TEST_WALK_UP=walk-up-value\n")
    monkeypatch.delenv("BOOTSTRAP_ENV_TEST_WALK_UP", raising=False)
    monkeypatch.delenv("SOOTHE_DAEMON_INVOCATION_DIR", raising=False)
    monkeypatch.delenv("SOOTHE_CLI_WORKSPACE", raising=False)
    monkeypatch.chdir(nested)

    assert bootstrap_dotenv() is True

    assert os.environ.get("BOOTSTRAP_ENV_TEST_WALK_UP") == "walk-up-value"


def test_bootstrap_dotenv_uses_invocation_dir_env(tmp_path, monkeypatch) -> None:
    project_root = tmp_path / "project"
    other_cwd = project_root / "other"
    other_cwd.mkdir(parents=True)
    (project_root / ".env").write_text("BOOTSTRAP_ENV_TEST_INVOCATION=invocation-value\n")
    monkeypatch.delenv("BOOTSTRAP_ENV_TEST_INVOCATION", raising=False)
    monkeypatch.delenv("SOOTHE_CLI_WORKSPACE", raising=False)
    monkeypatch.setenv("SOOTHE_DAEMON_INVOCATION_DIR", str(project_root))
    monkeypatch.chdir(other_cwd)

    assert bootstrap_dotenv() is True

    assert os.environ.get("BOOTSTRAP_ENV_TEST_INVOCATION") == "invocation-value"


def test_bootstrap_dotenv_shell_env_takes_precedence(tmp_path, monkeypatch) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()
    (project_root / ".env").write_text("BOOTSTRAP_ENV_TEST_PRECEDENCE=from-dotenv\n")
    monkeypatch.setenv("BOOTSTRAP_ENV_TEST_PRECEDENCE", "from-shell")
    monkeypatch.delenv("SOOTHE_DAEMON_INVOCATION_DIR", raising=False)
    monkeypatch.delenv("SOOTHE_CLI_WORKSPACE", raising=False)
    monkeypatch.chdir(project_root)

    bootstrap_dotenv()

    assert os.environ.get("BOOTSTRAP_ENV_TEST_PRECEDENCE") == "from-shell"


def test_bootstrap_dotenv_loads_soothe_home_env(tmp_path, monkeypatch) -> None:
    soothe_home = tmp_path / "soothe-home"
    soothe_home.mkdir()
    (soothe_home / ".env").write_text("BOOTSTRAP_ENV_TEST_HOME=home-value\n")
    project_root = tmp_path / "project"
    project_root.mkdir()
    monkeypatch.setenv("SOOTHE_HOME", str(soothe_home))
    monkeypatch.delenv("BOOTSTRAP_ENV_TEST_HOME", raising=False)
    monkeypatch.delenv("SOOTHE_DAEMON_INVOCATION_DIR", raising=False)
    monkeypatch.delenv("SOOTHE_CLI_WORKSPACE", raising=False)
    monkeypatch.chdir(project_root)

    assert bootstrap_dotenv() is True

    assert os.environ.get("BOOTSTRAP_ENV_TEST_HOME") == "home-value"
