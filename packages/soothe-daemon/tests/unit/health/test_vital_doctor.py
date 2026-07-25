"""Unit tests for vital progressive doctor health checks."""

from __future__ import annotations

from io import StringIO
from unittest.mock import MagicMock

import pytest

from soothe_daemon.health.checker import (
    DEEP_CATEGORIES,
    VITAL_CATEGORIES,
    HealthChecker,
)
from soothe_daemon.health.formatters import ProgressiveReporter
from soothe_daemon.health.models import CategoryResult, CheckResult, CheckStatus


@pytest.mark.asyncio
async def test_tool_deps_reports_rg_fd_git(monkeypatch: pytest.MonkeyPatch) -> None:
    from soothe_daemon.health.checks import tool_deps_check as mod

    def fake_which(name: str) -> str | None:
        return {
            "rg": "/usr/bin/rg",
            "fd": "/usr/bin/fd",
            "git": "/usr/bin/git",
        }.get(name)

    monkeypatch.setattr(mod.shutil, "which", fake_which)
    monkeypatch.setattr(mod, "_bin_version", lambda _p: "tool 14.0.0")

    result = await mod.check_tool_deps()
    assert result.category == "tool_deps"
    names = {c.name: c for c in result.checks}
    assert names["rg"].status == CheckStatus.OK
    assert names["fd"].status == CheckStatus.OK
    assert names["git"].status == CheckStatus.OK


@pytest.mark.asyncio
async def test_tool_deps_warns_when_rg_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    from soothe_daemon.health.checks import tool_deps_check as mod

    monkeypatch.setattr(mod.shutil, "which", lambda _name: None)

    result = await mod.check_tool_deps()
    names = {c.name: c for c in result.checks}
    assert names["rg"].status == CheckStatus.WARNING
    assert names["fd"].status == CheckStatus.WARNING
    assert "remediation" in names["rg"].details


@pytest.mark.asyncio
async def test_persistence_sqlite_skips_postgres_connection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from soothe_daemon.persistence import health_check as mod

    cfg = MagicMock()
    cfg.persistence.default_backend = "sqlite"
    cfg.persistence.postgres_base_dsn = None

    monkeypatch.setattr(
        mod,
        "_check_filesystem_permissions",
        lambda: CheckResult(name="filesystem_permissions", status=CheckStatus.OK, message="ok"),
    )
    monkeypatch.setattr(
        mod,
        "_check_disk_space",
        lambda: CheckResult(name="disk_space", status=CheckStatus.OK, message="ok"),
    )
    monkeypatch.setattr(
        mod,
        "_check_sqlite_backend",
        lambda _c: CheckResult(name="sqlite_backend", status=CheckStatus.OK, message="sqlite ok"),
    )

    result = await mod.check_persistence(cfg)
    names = {c.name for c in result.checks}
    assert "postgresql_connection" not in names
    assert "sqlite_backend" in names
    assert "default_backend" in names


@pytest.mark.asyncio
async def test_persistence_postgresql_requires_dsn() -> None:
    from soothe_daemon.persistence import health_check as mod

    cfg = MagicMock()
    cfg.persistence.default_backend = "postgresql"
    cfg.persistence.postgres_base_dsn = None
    cfg.persistence.postgres_databases = {}

    # Avoid real filesystem/home failures dominating
    result_conn = mod._check_postgresql_connection(cfg)
    assert result_conn.status == CheckStatus.ERROR
    assert "postgres_base_dsn" in result_conn.message


@pytest.mark.asyncio
async def test_providers_only_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    from soothe_daemon.health.checks import providers_check as mod

    p = MagicMock()
    p.name = "openrouter"
    p.api_key = "sk-test"
    p.provider_type = "openai"

    cfg = MagicMock()
    cfg.providers = [p]
    cfg.router.default = "openrouter:model"

    result = await mod.check_providers(cfg, live_llm=False)
    assert len(result.checks) == 1
    assert result.checks[0].name == "openrouter"
    assert result.checks[0].status == CheckStatus.OK


@pytest.mark.asyncio
async def test_observability_skips_when_langfuse_disabled() -> None:
    from soothe_daemon.health.checks import observability_check as mod

    cfg = MagicMock()
    cfg.observability.langfuse.enabled = False

    result = await mod.check_observability(cfg)
    assert result.checks[0].status == CheckStatus.SKIPPED
    assert result.checks[0].name == "langfuse"


@pytest.mark.asyncio
async def test_vital_categories_default(monkeypatch: pytest.MonkeyPatch) -> None:
    checker = HealthChecker()
    seen: list[str] = []

    method_by_cat = {
        "configuration": "check_config",
        "tool_deps": "check_tool_deps",
        "daemon": "check_daemon",
        "persistence": "check_persistence",
        "protocols": "check_protocols",
        "vector_stores": "check_vector_stores",
        "providers": "check_providers",
        "mcp_servers": "check_mcp_servers",
        "models": "check_models",
        "external_apis": "check_external_apis",
        "observability": "check_observability",
    }

    for cat, method_name in method_by_cat.items():

        async def _make(*_a: object, n: str = cat, **_k: object) -> CategoryResult:
            seen.append(n)
            return CategoryResult(category=n, status=CheckStatus.OK, checks=[])

        monkeypatch.setattr(checker, method_name, _make)

    report = await checker.run_all_checks()
    assert [c.category for c in report.categories] == VITAL_CATEGORIES
    assert "external_apis" not in [c.category for c in report.categories]

    seen.clear()
    report_deep = await checker.run_all_checks(deep=True)
    assert [c.category for c in report_deep.categories] == [
        *VITAL_CATEGORIES,
        *DEEP_CATEGORIES,
    ]


def test_progressive_reporter_streams_categories() -> None:
    buf = StringIO()
    reporter = ProgressiveReporter(use_color=False, stream=buf)
    reporter.category_start("tool_deps")
    reporter.category_done(
        CategoryResult(
            category="tool_deps",
            status=CheckStatus.WARNING,
            checks=[
                CheckResult(
                    name="rg",
                    status=CheckStatus.WARNING,
                    message="rg missing",
                    details={"remediation": "install ripgrep"},
                )
            ],
        )
    )
    from soothe_daemon.health.models import HealthReport

    reporter.finish(
        HealthReport(
            timestamp="t",
            soothe_version="0",
            config_path=None,
            overall_status=CheckStatus.WARNING,
            categories=[],
        )
    )
    text = buf.getvalue()
    assert "progressive diagnosis" in text
    assert "▸ Tool Deps" in text
    assert "rg missing" in text
    assert "Remediation: install ripgrep" in text
    assert "Overall Status" in text
