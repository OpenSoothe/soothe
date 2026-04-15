"""Health check orchestration."""

import asyncio
from datetime import UTC, datetime
from importlib.metadata import version as get_version
from typing import Any

from soothe.config import SootheConfig

from soothe.daemon.health.formatters import aggregate_status
from soothe.daemon.health.models import CategoryResult, CheckStatus, HealthReport


class HealthChecker:
    """Orchestrates health checks across all categories.

    This class provides a unified interface for running health checks
    on various Soothe components including configuration, daemon,
    persistence, providers, and external services.

    Attributes:
        config: SootheConfig instance for config-driven checks (optional)
    """

    def __init__(self, config: SootheConfig | None = None) -> None:
        """Initialize health checker.

        Args:
            config: SootheConfig instance. If None, runs basic checks
                that don't require configuration.
        """
        self.config = config

    async def run_all_checks(
        self,
        categories: list[str] | None = None,
        exclude: list[str] | None = None,
    ) -> HealthReport:
        """Run all health checks asynchronously.

        Args:
            categories: Specific categories to run (None = all categories)
            exclude: Categories to skip

        Returns:
            Complete health report with all check results
        """
        # Default to all categories
        all_categories = [
            "configuration",
            "daemon",
            "persistence",
            "protocols",
            "vector_stores",
            "providers",
            "mcp_servers",
            "external_apis",
            "observability",
        ]

        # Filter categories
        selected = [c for c in all_categories if c in categories] if categories else all_categories

        if exclude:
            selected = [c for c in selected if c not in exclude]

        # Map category names to check methods
        check_methods: dict[str, Any] = {
            "configuration": self.check_config,
            "daemon": self.check_daemon,
            "persistence": self.check_persistence,
            "protocols": self.check_protocols,
            "vector_stores": self.check_vector_stores,
            "providers": self.check_providers,
            "mcp_servers": self.check_mcp_servers,
            "external_apis": self.check_external_apis,
            "observability": self.check_observability,
        }

        # Run selected checks in parallel
        tasks = [check_methods[category]() for category in selected if category in check_methods]

        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Process results
        category_results = []
        for i, result in enumerate(results):
            category_name = selected[i]

            if isinstance(result, Exception):
                # Check method raised an exception
                category_results.append(
                    CategoryResult(
                        category=category_name,
                        status=CheckStatus.ERROR,
                        checks=[],
                        message=f"Check failed with exception: {result}",
                    )
                )
            elif isinstance(result, CategoryResult):
                category_results.append(result)
            else:
                # Unexpected result type
                category_results.append(
                    CategoryResult(
                        category=category_name,
                        status=CheckStatus.ERROR,
                        checks=[],
                        message=f"Unexpected result type: {type(result)}",
                    )
                )

        # Calculate overall status
        overall_status = aggregate_status([cat.status for cat in category_results])

        # Build report
        soothe_version = get_version("soothe")
        config_path = (
            str(self.config.config_path)
            if self.config and hasattr(self.config, "config_path")
            else None
        )

        return HealthReport(
            timestamp=datetime.now(UTC).isoformat(),
            soothe_version=soothe_version,
            config_path=config_path,
            overall_status=overall_status,
            categories=category_results,
        )

    async def check_config(self) -> CategoryResult:
        """Check configuration format and values.

        Returns:
            CategoryResult with config check results
        """
        from soothe.daemon.health.checks.config_check import check_config

        return await check_config(self.config)

    async def check_daemon(self) -> CategoryResult:
        """Check daemon health.

        Returns:
            CategoryResult with daemon check results
        """
        from soothe.daemon.health.checks.daemon_check import check_daemon

        return await check_daemon(self.config)

    async def check_persistence(self) -> CategoryResult:
        """Check persistence layer (PostgreSQL, RocksDB, filesystem).

        Returns:
            CategoryResult with persistence check results
        """
        from soothe.daemon.health.checks.persistence_check import check_persistence

        return await check_persistence(self.config)

    async def check_protocols(self) -> CategoryResult:
        """Check protocol backends.

        Returns:
            CategoryResult with protocol check results
        """
        from soothe.daemon.health.checks.protocols_check import check_protocols

        return await check_protocols(self.config)

    async def check_vector_stores(self) -> CategoryResult:
        """Check vector store backends.

        Returns:
            CategoryResult with vector store check results
        """
        from soothe.daemon.health.checks.vector_stores_check import check_vector_stores

        return await check_vector_stores(self.config)

    async def check_providers(self) -> CategoryResult:
        """Check LLM provider connectivity.

        Returns:
            CategoryResult with provider check results
        """
        from soothe.daemon.health.checks.providers_check import check_providers

        return await check_providers(self.config)

    async def check_mcp_servers(self) -> CategoryResult:
        """Check MCP servers.

        Returns:
            CategoryResult with MCP server check results
        """
        from soothe.daemon.health.checks.mcp_check import check_mcp_servers

        return await check_mcp_servers(self.config)

    async def check_external_apis(self) -> CategoryResult:
        """Check external API connectivity.

        Returns:
            CategoryResult with external API check results
        """
        from soothe.daemon.health.checks.external_apis_check import check_external_apis

        return await check_external_apis(self.config)

    async def check_observability(self) -> CategoryResult:
        """Check observability and tracing configuration.

        Returns:
            CategoryResult with observability check results
        """
        from soothe.daemon.health.checks.observability_check import check_observability

        return await check_observability(self.config)
