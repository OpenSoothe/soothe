"""Regression: split templates compose and nano template loads alone."""

from __future__ import annotations

from pathlib import Path

import pytest

from soothe.config import SootheConfig


def _repo_root() -> Path:
    # packages/soothe/tests/unit/config/test_template_yaml.py → repo root
    return Path(__file__).resolve().parents[5]


def _nano_template_path() -> Path:
    return _repo_root() / "config" / "templates" / "nano.yml"


def _soothe_template_path() -> Path:
    return _repo_root() / "config" / "templates" / "soothe.yml"


@pytest.mark.skipif(not _nano_template_path().is_file(), reason="nano template not in checkout")
def test_nano_template_loads_as_single_file(monkeypatch: pytest.MonkeyPatch) -> None:
    """Nano template is nano-owned and loads via ``from_yaml_file``."""
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    monkeypatch.delenv("SOOTHE_POSTGRES_BASE_DSN", raising=False)
    monkeypatch.delenv("SOOTHE_POSTGRES_DSN", raising=False)
    monkeypatch.delenv("LANGFUSE_PUBLIC_KEY", raising=False)
    monkeypatch.delenv("LANGFUSE_SECRET_KEY", raising=False)
    monkeypatch.delenv("LANGFUSE_HOST", raising=False)
    monkeypatch.delenv("DEEPXIV_API_KEY", raising=False)

    loaded = SootheConfig.from_yaml_file(str(_nano_template_path()))
    assert len(loaded.providers) >= 1
    assert loaded.vector_store_router.default == "sqlite_vec_default:soothe_default"
    assert loaded.persistence.postgres_base_dsn == "${SOOTHE_POSTGRES_BASE_DSN}"
    assert loaded.tools.deepxiv.token == "${DEEPXIV_API_KEY}"


@pytest.mark.skipif(
    not (_nano_template_path().is_file() and _soothe_template_path().is_file()),
    reason="split templates not in checkout",
)
def test_split_templates_compose(monkeypatch: pytest.MonkeyPatch) -> None:
    """nano.yml + soothe.yml compose into a full host config."""
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    monkeypatch.delenv("SOOTHE_SMTP_PASSWORD", raising=False)
    monkeypatch.delenv("FEISHU_APP_SECRET", raising=False)

    loaded = SootheConfig.from_split_yaml_files(
        nano_path=str(_nano_template_path()),
        soothe_path=str(_soothe_template_path()),
    )
    assert loaded.providers
    assert loaded.agent.loop.enabled is True
    assert loaded.cron.max_jobs == 100
    assert loaded.vector_store_router.default == "sqlite_vec_default:soothe_default"
    assert loaded.agent.autopilot.notify.sinks.email.smtp_password == "${SOOTHE_SMTP_PASSWORD}"
    assert loaded.agent.autopilot.notify.sinks.feishu.app_secret == "${FEISHU_APP_SECRET}"
