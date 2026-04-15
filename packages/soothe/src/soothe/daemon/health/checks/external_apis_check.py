"""External API connectivity health check implementation."""

import asyncio
import urllib.request

from soothe.config import SootheConfig

from soothe.daemon.health.formatters import aggregate_status
from soothe.daemon.health.models import CategoryResult, CheckResult, CheckStatus


def _check_api_reachability(
    name: str,
    url: str,
    timeout: float = 2.0,
) -> CheckResult:
    """Check if an external API is reachable.

    Args:
        name: Human-readable API name
        url: URL to check (will use HEAD request)
        timeout: Request timeout in seconds

    Returns:
        CheckResult with reachability status
    """
    try:
        req = urllib.request.Request(url, method="HEAD")  # noqa: S310
        req.add_header("User-Agent", "Soothe-HealthCheck/1.0")

        with urllib.request.urlopen(req, timeout=timeout) as response:  # noqa: S310
            if response.status in (200, 301, 302, 403, 404):
                # 403/404 still means server is reachable
                return CheckResult(
                    name=name,
                    status=CheckStatus.OK,
                    message=f"{name} API reachable",
                )
            return CheckResult(
                name=name,
                status=CheckStatus.WARNING,
                message=f"{name} API returned status {response.status}",
            )

    except urllib.error.URLError as e:
        return CheckResult(
            name=name,
            status=CheckStatus.ERROR,
            message=f"{name} API unreachable: {e.reason}",
            details={"url": url, "remediation": f"Check network connectivity and {name} status"},
        )
    except Exception as e:
        return CheckResult(
            name=name,
            status=CheckStatus.WARNING,
            message=f"{name} API check failed: {e}",
        )


def _check_openai_api() -> CheckResult:
    """Check OpenAI API reachability."""
    return _check_api_reachability("OpenAI", "https://api.openai.com")


def _check_google_api() -> CheckResult:
    """Check Google API reachability."""
    return _check_api_reachability("Google", "https://generativelanguage.googleapis.com")


def _check_tavily_api() -> CheckResult:
    """Check Tavily API reachability."""
    return _check_api_reachability("Tavily", "https://api.tavily.com")


def _check_serper_api() -> CheckResult:
    """Check Serper API reachability."""
    return _check_api_reachability("Serper", "https://google.serper.dev")


def _check_jina_api() -> CheckResult:
    """Check Jina API reachability."""
    return _check_api_reachability("Jina", "https://api.jina.ai")


def _check_browser_runtime() -> CheckResult:
    """Check browser runtime for web search capabilities."""
    try:
        from webdriver_manager.chrome import ChromeDriverManager

        # Try to get ChromeDriver
        try:
            driver_path = ChromeDriverManager().install()
            return CheckResult(
                name="browser_runtime",
                status=CheckStatus.OK,
                message="Chrome and ChromeDriver available",
                details={"driver_path": driver_path},
            )
        except Exception as e:
            return CheckResult(
                name="browser_runtime",
                status=CheckStatus.WARNING,
                message=f"ChromeDriver setup issue: {e}",
                details={"remediation": "Install Chrome and run: pip install webdriver-manager"},
            )

    except ImportError:
        return CheckResult(
            name="browser_runtime",
            status=CheckStatus.INFO,
            message="Browser automation not installed (optional)",
            details={"remediation": "Install selenium and webdriver-manager for web search"},
        )


async def check_external_apis(config: SootheConfig | None = None) -> CategoryResult:  # noqa: ARG001
    """Check external API connectivity (optional services).

    Tests reachability of external APIs used by Soothe for
    web search, research, and other capabilities.

    These are OPTIONAL services - timeouts/unavailability should be INFO/WARNING,
    not ERROR, as they don't affect core functionality.

    Args:
        config: SootheConfig instance (not used for external API checks)

    Returns:
        CategoryResult with external API check results
    """
    # Run all API checks in parallel using asyncio
    # Since urllib.request is sync, we run in executor
    loop = asyncio.get_event_loop()

    tasks = [
        loop.run_in_executor(None, _check_openai_api),
        loop.run_in_executor(None, _check_google_api),
        loop.run_in_executor(None, _check_tavily_api),
        loop.run_in_executor(None, _check_serper_api),
        loop.run_in_executor(None, _check_jina_api),
        loop.run_in_executor(None, _check_browser_runtime),
    ]

    checks = await asyncio.gather(*tasks)

    # For optional services, downgrade ERROR to INFO (not critical)
    # Only keep ERROR if it's a configuration issue
    adjusted_checks = []
    for check in checks:
        if check.status == CheckStatus.ERROR and check.name in (
            "OpenAI",
            "Google",
            "Tavily",
            "Serper",
            "Jina",
        ):
            # Downgrade unreachable external APIs from ERROR to INFO
            msg = check.message.split(":")[1].strip() if ":" in check.message else check.message
            adjusted_checks.append(
                CheckResult(
                    name=check.name,
                    status=CheckStatus.INFO,
                    message=f"{check.name} API: {msg}",
                    details={"optional": True, **check.details},
                )
            )
        else:
            adjusted_checks.append(check)

    overall_status = aggregate_status([check.status for check in adjusted_checks])

    return CategoryResult(
        category="external_apis",
        status=overall_status,
        checks=adjusted_checks,
        message="(optional for basic usage)",
    )
