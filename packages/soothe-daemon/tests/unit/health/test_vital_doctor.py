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
from soothe_daemon.health.models import (
    CategoryResult,
    CheckResult,
    CheckStatus,
    category_result_from_dict,
)


@pytest.mark.asyncio
async def test_tool_deps_via_nano_diagnose(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_nano(_config=None, **kwargs):
        assert kwargs.get("categories") == ["tool_deps"]
        return [
            {
                "category": "tool_deps",
                "status": "ok",
                "checks": [
                    {"name": "rg", "status": "ok", "message": "rg ok", "details": {}},
                    {"name": "fd", "status": "ok", "message": "fd ok", "details": {}},
                    {"name": "git", "status": "ok", "message": "git ok", "details": {}},
                ],
                "message": None,
            }
        ]

    monkeypatch.setattr("soothe_nano.diagnose.diagnose", fake_nano)
    checker = HealthChecker()
    result = await checker.check_tool_deps()
    assert result.category == "tool_deps"
    assert {c.name for c in result.checks} == {"rg", "fd", "git"}


@pytest.mark.asyncio
async def test_host_via_soothe_diagnose(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_host(_config=None, **kwargs):
        assert kwargs.get("categories") == ["host"]
        return [
            {
                "category": "host",
                "status": "ok",
                "checks": [
                    {
                        "name": "autopilot",
                        "status": "ok",
                        "message": "ok",
                        "details": {},
                    }
                ],
                "message": None,
            }
        ]

    monkeypatch.setattr("soothe.diagnose.diagnose", fake_host)
    checker = HealthChecker()
    result = await checker.check_host()
    assert result.category == "host"
    assert result.checks[0].name == "autopilot"


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

    result_conn = mod._check_postgresql_connection(cfg)
    assert result_conn.status == CheckStatus.ERROR
    assert "postgres_base_dsn" in result_conn.message


@pytest.mark.asyncio
async def test_providers_delegates_to_nano(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_nano(_config=None, **kwargs):
        assert kwargs.get("live_llm") is False
        return [
            {
                "category": "providers",
                "status": "ok",
                "checks": [
                    {
                        "name": "openrouter",
                        "status": "ok",
                        "message": "ok",
                        "details": {},
                    }
                ],
                "message": None,
            }
        ]

    monkeypatch.setattr("soothe_nano.diagnose.diagnose", fake_nano)
    checker = HealthChecker()
    result = await checker.check_providers(live_llm=False)
    assert result.checks[0].name == "openrouter"


@pytest.mark.asyncio
async def test_observability_delegates_to_nano(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_nano(_config=None, **_kwargs):
        return [
            {
                "category": "observability",
                "status": "skipped",
                "checks": [
                    {
                        "name": "langfuse",
                        "status": "skipped",
                        "message": "disabled",
                        "details": {},
                    }
                ],
                "message": None,
            }
        ]

    monkeypatch.setattr("soothe_nano.diagnose.diagnose", fake_nano)
    checker = HealthChecker()
    result = await checker.check_observability()
    assert result.checks[0].name == "langfuse"
    assert result.checks[0].status == CheckStatus.SKIPPED


@pytest.mark.asyncio
async def test_vital_categories_default(monkeypatch: pytest.MonkeyPatch) -> None:
    checker = HealthChecker()

    async def fake_nano(_config=None, **kwargs):
        cats = kwargs.get("categories") or []
        return [{"category": c, "status": "ok", "checks": [], "message": None} for c in cats]

    async def fake_host(_config=None, **kwargs):
        cats = kwargs.get("categories") or []
        return [{"category": c, "status": "ok", "checks": [], "message": None} for c in cats]

    monkeypatch.setattr("soothe_nano.diagnose.diagnose", fake_nano)
    monkeypatch.setattr("soothe.diagnose.diagnose", fake_host)

    local_methods = {
        "check_config": "configuration",
        "check_daemon": "daemon",
        "check_persistence": "persistence",
        "check_external_apis": "external_apis",
    }
    for method_name, cat in local_methods.items():

        async def _ok(*_a: object, n: str = cat, **_k: object) -> CategoryResult:
            return CategoryResult(category=n, status=CheckStatus.OK, checks=[])

        monkeypatch.setattr(checker, method_name, _ok)

    report = await checker.run_all_checks()
    assert [c.category for c in report.categories] == VITAL_CATEGORIES
    assert "host" in VITAL_CATEGORIES
    assert "external_apis" not in [c.category for c in report.categories]

    report_deep = await checker.run_all_checks(deep=True)
    assert [c.category for c in report_deep.categories] == [
        *VITAL_CATEGORIES,
        *DEEP_CATEGORIES,
    ]


def test_category_result_from_dict() -> None:
    result = category_result_from_dict(
        {
            "category": "tool_deps",
            "status": "warning",
            "checks": [
                {
                    "name": "rg",
                    "status": "warning",
                    "message": "missing",
                    "details": {"remediation": "install"},
                }
            ],
            "message": None,
        }
    )
    assert result.category == "tool_deps"
    assert result.status == CheckStatus.WARNING
    assert result.checks[0].details["remediation"] == "install"


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
