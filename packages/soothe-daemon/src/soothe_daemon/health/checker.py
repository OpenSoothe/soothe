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
from soothe_daemon.health.models import (
    CategoryResult,
    CheckStatus,
    HealthReport,
    category_result_from_dict,
)

# Default vitals — answer "can soothed run agent work?"
VITAL_CATEGORIES: list[str] = [
    "configuration",
    "tool_deps",
    "persistence",
    "providers",
    "observability",
    "host",
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

# Categories owned by soothe_nano.diagnose
_NANO_CATEGORIES: frozenset[str] = frozenset(
    {
        "tool_deps",
        "providers",
        "observability",
        "mcp_servers",
        "vector_stores",
        "models",
        "protocols",
    }
)

# Categories owned by soothe.diagnose
_HOST_CATEGORIES: frozenset[str] = frozenset({"host"})


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
        self._nano_cache: dict[str, CategoryResult] | None = None
        self._host_cache: dict[str, CategoryResult] | None = None
        self._nano_live_llm: bool | None = None

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

    async def _ensure_nano(
        self,
        selected: list[str],
        *,
        live_llm: bool,
    ) -> dict[str, CategoryResult]:
        """Lazily run nano.diagnose once per report for requested nano categories."""
        needed = [c for c in selected if c in _NANO_CATEGORIES]
        if not needed:
            return {}
        if self._nano_cache is not None and self._nano_live_llm == live_llm:
            return self._nano_cache

        from soothe_nano.diagnose import diagnose as nano_diagnose

        raw = await nano_diagnose(
            self.config,
            live_llm=live_llm,
            categories=needed,
        )
        cache = {item["category"]: category_result_from_dict(item) for item in raw}
        self._nano_cache = cache
        self._nano_live_llm = live_llm
        return cache

    async def _ensure_host(self, selected: list[str]) -> dict[str, CategoryResult]:
        """Lazily run soothe.diagnose once per report for requested host categories."""
        needed = [c for c in selected if c in _HOST_CATEGORIES]
        if not needed:
            return {}
        if self._host_cache is not None:
            return self._host_cache

        from soothe.diagnose import diagnose as host_diagnose

        raw = await host_diagnose(self.config, categories=needed)
        cache = {item["category"]: category_result_from_dict(item) for item in raw}
        self._host_cache = cache
        return cache

    async def _category_from_packages(
        self,
        category_name: str,
        selected: list[str],
        *,
        live_llm: bool,
    ) -> CategoryResult | None:
        if category_name in _NANO_CATEGORIES:
            nano = await self._ensure_nano(selected, live_llm=live_llm)
            result = nano.get(category_name)
            if result is not None:
                return result
            return CategoryResult(
                category=category_name,
                status=CheckStatus.ERROR,
                checks=[],
                message=f"nano diagnose did not return category: {category_name}",
            )
        if category_name in _HOST_CATEGORIES:
            host = await self._ensure_host(selected)
            result = host.get(category_name)
            if result is not None:
                return result
            return CategoryResult(
                category=category_name,
                status=CheckStatus.ERROR,
                checks=[],
                message=f"host diagnose did not return category: {category_name}",
            )
        return None

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

        Categories run sequentially (vital narrative order). Package diagnose
        APIs are batched per owner once per report.

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
        self._nano_cache = None
        self._host_cache = None
        self._nano_live_llm = None

        check_methods: dict[str, Callable[[], Awaitable[CategoryResult]]] = {
            "configuration": self.check_config,
            "daemon": lambda: self.check_daemon(require_running=require_running),
            "persistence": self.check_persistence,
            "external_apis": self.check_external_apis,
        }

        category_results: list[CategoryResult] = []
        for category_name in selected:
            if on_progress is not None:
                on_progress.category_start(category_name)

            try:
                packaged = await self._category_from_packages(
                    category_name,
                    selected,
                    live_llm=live_llm,
                )
                if packaged is not None:
                    result = packaged
                else:
                    method = check_methods.get(category_name)
                    if method is None:
                        result = CategoryResult(
                            category=category_name,
                            status=CheckStatus.ERROR,
                            checks=[],
                            message=f"Unknown category: {category_name}",
                        )
                    else:
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
        """Check host tool binaries via nano diagnose."""
        return await self._single_nano("tool_deps")

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
        """Check protocol backends via nano diagnose."""
        return await self._single_nano("protocols")

    async def check_vector_stores(self) -> CategoryResult:
        """Check vector store backends via nano diagnose."""
        return await self._single_nano("vector_stores")

    async def check_providers(self, *, live_llm: bool = False) -> CategoryResult:
        """Check LLM provider credentials via nano diagnose."""
        return await self._single_nano("providers", live_llm=live_llm)

    async def check_mcp_servers(self) -> CategoryResult:
        """Check MCP servers via nano diagnose."""
        return await self._single_nano("mcp_servers")

    async def check_models(self) -> CategoryResult:
        """Check embedding router role via nano diagnose."""
        return await self._single_nano("models")

    async def check_host(self) -> CategoryResult:
        """Check host orchestration features via soothe diagnose."""
        host = await self._ensure_host(["host"])
        result = host.get("host")
        if result is not None:
            return result
        return CategoryResult(
            category="host",
            status=CheckStatus.ERROR,
            checks=[],
            message="host diagnose did not return category: host",
        )

    async def check_external_apis(self) -> CategoryResult:
        """Check config-gated optional external API reachability."""
        from soothe_daemon.health.checks.external_apis_check import check_external_apis

        return await check_external_apis(self.config)

    async def check_observability(self) -> CategoryResult:
        """Check observability via nano diagnose."""
        return await self._single_nano("observability")

    async def _single_nano(
        self,
        category: str,
        *,
        live_llm: bool = False,
    ) -> CategoryResult:
        nano = await self._ensure_nano([category], live_llm=live_llm)
        result = nano.get(category)
        if result is not None:
            return result
        return CategoryResult(
            category=category,
            status=CheckStatus.ERROR,
            checks=[],
            message=f"nano diagnose did not return category: {category}",
        )


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
