"""Health check orchestration."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from importlib.metadata import version as get_version
from typing import Protocol

from soothe.config import SootheConfig

from soothe_daemon import __version__ as daemon_version
from soothe_daemon.config import SootheDaemonConfig
from soothe_daemon.health.formatters import aggregate_status
from soothe_daemon.health.models import CategoryResult, CheckStatus, HealthReport

# Default vitals — answer "can soothed run agent work?"
VITAL_CATEGORIES: list[str] = [
    "configuration",
    "tool_deps",
    "persistence",
    "providers",
    "observability",
    "daemon",
]

# Optional / deep diagnostics (enabled via --deep or explicit --category)
DEEP_CATEGORIES: list[str] = [
    "protocols",
    "vector_stores",
    "mcp_servers",
    "models",
    "external_apis",
]

ALL_CATEGORIES: list[str] = [*VITAL_CATEGORIES, *DEEP_CATEGORIES]


class DoctorProgress(Protocol):
    """Progress callbacks for progressive diagnosis display."""

    def category_start(self, category: str) -> None:
        """Called before a category begins."""

    def category_done(self, result: CategoryResult) -> None:
        """Called after a category completes."""


class HealthChecker:
    """Orchestrates health checks across vital (and optional deep) categories.

    Attributes:
        config: Agent ``SootheConfig`` for config-driven checks (optional).
        daemon_config: Daemon ``SootheDaemonConfig`` for transport checks (optional).
    """

    def __init__(
        self,
        config: SootheConfig | None = None,
        daemon_config: SootheDaemonConfig | None = None,
    ) -> None:
        """Initialize health checker.

        Args:
            config: Agent ``SootheConfig``. If ``None``, runs basic checks
                that don't require configuration.
            daemon_config: Daemon ``SootheDaemonConfig`` for transport /
                worker-pool / queue checks. If ``None``, daemon-side checks
                fall back to defaults.
        """
        self.config = config
        self.daemon_config = daemon_config

    def _resolve_categories(
        self,
        categories: list[str] | None,
        exclude: list[str] | None,
        *,
        deep: bool,
    ) -> list[str]:
        if categories:
            selected = [c for c in categories if c in ALL_CATEGORIES]
            # Preserve caller order but keep known names only; allow unknown to surface as error
            unknown = [c for c in categories if c not in ALL_CATEGORIES]
            selected = [*selected, *unknown]
        else:
            selected = list(VITAL_CATEGORIES)
            if deep:
                selected.extend(DEEP_CATEGORIES)

        if exclude:
            selected = [c for c in selected if c not in exclude]
        return selected

    async def run_all_checks(
        self,
        categories: list[str] | None = None,
        exclude: list[str] | None = None,
        *,
        deep: bool = False,
        live_llm: bool = False,
        require_running: bool = False,
        on_progress: DoctorProgress | None = None,
    ) -> HealthReport:
        """Run health checks, optionally streaming progressive category updates.

        Categories run sequentially (vital narrative order). Individual check
        modules may still parallelize internally.

        Args:
            categories: Specific categories to run (None = vitals, or vitals+deep).
            exclude: Categories to skip.
            deep: Include deep optional categories when ``categories`` is None.
            live_llm: Perform a live invoke against ``router.default``.
            require_running: Treat offline daemon as error (via daemon check message).
            on_progress: Optional progressive diagnosis callbacks.

        Returns:
            Complete health report with all check results.
        """
        selected = self._resolve_categories(categories, exclude, deep=deep)

        check_methods: dict[str, Callable[[], Awaitable[CategoryResult]]] = {
            "configuration": self.check_config,
            "tool_deps": self.check_tool_deps,
            "daemon": lambda: self.check_daemon(require_running=require_running),
            "persistence": self.check_persistence,
            "protocols": self.check_protocols,
            "vector_stores": self.check_vector_stores,
            "providers": lambda: self.check_providers(live_llm=live_llm),
            "mcp_servers": self.check_mcp_servers,
            "models": self.check_models,
            "external_apis": self.check_external_apis,
            "observability": self.check_observability,
        }

        category_results: list[CategoryResult] = []
        for category_name in selected:
            method = check_methods.get(category_name)
            if on_progress is not None:
                on_progress.category_start(category_name)

            if method is None:
                result = CategoryResult(
                    category=category_name,
                    status=CheckStatus.ERROR,
                    checks=[],
                    message=f"Unknown category: {category_name}",
                )
            else:
                try:
                    result = await method()
                except Exception as exc:
                    result = CategoryResult(
                        category=category_name,
                        status=CheckStatus.ERROR,
                        checks=[],
                        message=f"Check failed with exception: {exc}",
                    )

            if on_progress is not None:
                on_progress.category_done(result)
            category_results.append(result)

        overall_status = aggregate_status([cat.status for cat in category_results])

        soothe_version = get_version("soothe")
        config_path = (
            str(self.config.config_path)
            if self.config and hasattr(self.config, "config_path")
            else None
        )

        return HealthReport(
            timestamp=datetime.now(UTC).isoformat(),
            soothe_version=soothe_version,
            daemon_version=daemon_version,
            config_path=config_path,
            overall_status=overall_status,
            categories=category_results,
        )

    async def check_config(self) -> CategoryResult:
        """Check configuration format and values."""
        from soothe_daemon.health.checks.config_check import check_config

        return await check_config(self.config)

    async def check_tool_deps(self) -> CategoryResult:
        """Check host tool binaries (rg, fd, git)."""
        from soothe_daemon.health.checks.tool_deps_check import check_tool_deps

        return await check_tool_deps()

    async def check_daemon(self, *, require_running: bool = False) -> CategoryResult:
        """Check daemon health."""
        from soothe_daemon.health.checks.daemon_check import check_daemon

        result = await check_daemon(self.daemon_config)
        if require_running:
            result = _upgrade_offline_daemon_to_error(result)
        return result

    async def check_persistence(self) -> CategoryResult:
        """Check persistence layer (PostgreSQL or SQLite)."""
        from soothe_daemon.persistence.health_check import check_persistence

        return await check_persistence(self.config)

    async def check_protocols(self) -> CategoryResult:
        """Check protocol backends."""
        from soothe_daemon.health.checks.protocols_check import check_protocols

        return await check_protocols(self.config)

    async def check_vector_stores(self) -> CategoryResult:
        """Check vector store backends."""
        from soothe_daemon.health.checks.vector_stores_check import check_vector_stores

        return await check_vector_stores(self.config)

    async def check_providers(self, *, live_llm: bool = False) -> CategoryResult:
        """Check LLM provider credentials (optional live invoke)."""
        from soothe_daemon.health.checks.providers_check import check_providers

        return await check_providers(self.config, live_llm=live_llm)

    async def check_mcp_servers(self) -> CategoryResult:
        """Check MCP servers."""
        from soothe_daemon.health.checks.mcp_check import check_mcp_servers

        return await check_mcp_servers(self.config)

    async def check_models(self) -> CategoryResult:
        """Check embedding router role configuration."""
        from soothe_daemon.health.checks.embedding_role_check import check_embedding_role

        return await check_embedding_role(self.config)

    async def check_external_apis(self) -> CategoryResult:
        """Check config-gated optional external API reachability."""
        from soothe_daemon.health.checks.external_apis_check import check_external_apis

        return await check_external_apis(self.config)

    async def check_observability(self) -> CategoryResult:
        """Check observability and tracing configuration."""
        from soothe_daemon.health.checks.observability_check import check_observability

        return await check_observability(self.config)


def _upgrade_offline_daemon_to_error(result: CategoryResult) -> CategoryResult:
    """When ``--require-running``, treat offline daemon INFO checks as ERROR."""
    from soothe_daemon.health.models import CheckResult

    upgraded: list[CheckResult] = []
    for check in result.checks:
        if check.status == CheckStatus.INFO and any(
            token in check.message.lower()
            for token in ("not running", "not found", "not accepting")
        ):
            upgraded.append(
                CheckResult(
                    name=check.name,
                    status=CheckStatus.ERROR,
                    message=check.message,
                    details={
                        **check.details,
                        "remediation": "Start the daemon with `soothed start`",
                    },
                )
            )
        else:
            upgraded.append(check)

    return CategoryResult(
        category=result.category,
        status=aggregate_status([c.status for c in upgraded]),
        checks=upgraded,
        message=result.message,
    )
