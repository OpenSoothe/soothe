"""External API connectivity health check (config-gated, deep mode)."""

from __future__ import annotations

import asyncio
import urllib.error
import urllib.request

from soothe.config import SootheConfig

from soothe_daemon.health.formatters import aggregate_status
from soothe_daemon.health.models import CategoryResult, CheckResult, CheckStatus

# Known optional SaaS endpoints — only probed when credentials/config hint use.
_API_ENDPOINTS: dict[str, str] = {
    "tavily": "https://api.tavily.com",
    "serper": "https://google.serper.dev",
    "jina": "https://api.jina.ai",
}


def _check_api_reachability(
    name: str,
    url: str,
    timeout: float = 2.0,
) -> CheckResult:
    """Check if an external API is reachable via HEAD."""
    try:
        req = urllib.request.Request(url, method="HEAD")  # noqa: S310
        req.add_header("User-Agent", "Soothe-Doctor/1.0")

        with urllib.request.urlopen(req, timeout=timeout) as response:  # noqa: S310
            if response.status in (200, 301, 302, 403, 404):
                return CheckResult(
                    name=name,
                    status=CheckStatus.OK,
                    message=f"{name} API reachable",
                    details={"url": url, "optional": True},
                )
            return CheckResult(
                name=name,
                status=CheckStatus.WARNING,
                message=f"{name} API returned status {response.status}",
                details={"url": url, "optional": True},
            )

    except urllib.error.URLError as e:
        return CheckResult(
            name=name,
            status=CheckStatus.INFO,
            message=f"{name} API unreachable: {e.reason}",
            details={
                "url": url,
                "optional": True,
                "remediation": f"Check network connectivity and {name} status",
            },
        )
    except Exception as e:
        return CheckResult(
            name=name,
            status=CheckStatus.INFO,
            message=f"{name} API check failed: {e}",
            details={"url": url, "optional": True},
        )


def _env_present(name: str) -> bool:
    import os

    return bool(os.environ.get(name, "").strip())


def _configured_optional_apis(config: SootheConfig | None) -> list[tuple[str, str]]:
    """Return (name, url) pairs for optional APIs hinted by env/config."""
    selected: list[tuple[str, str]] = []

    # Env-key heuristics for optional research/search APIs (not content judgment).
    env_map = {
        "tavily": "TAVILY_API_KEY",
        "serper": "SERPER_API_KEY",
        "jina": "JINA_API_KEY",
    }
    for name, env_name in env_map.items():
        if _env_present(env_name):
            selected.append((name, _API_ENDPOINTS[name]))

    # Provider base URLs already covered by providers category; include openai/google
    # reachability only when those providers are configured.
    if config is not None:
        provider_names = {p.name.lower() for p in config.providers}
        if "openai" in provider_names:
            selected.append(("openai", "https://api.openai.com"))
        if "google" in provider_names or "gemini" in provider_names:
            selected.append(("google", "https://generativelanguage.googleapis.com"))

    # Dedupe by name preserving order
    seen: set[str] = set()
    unique: list[tuple[str, str]] = []
    for name, url in selected:
        if name not in seen:
            seen.add(name)
            unique.append((name, url))
    return unique


async def check_external_apis(config: SootheConfig | None = None) -> CategoryResult:
    """Check optional external API reachability when credentials/config imply use.

    Args:
        config: SootheConfig instance.

    Returns:
        CategoryResult with external API check results.
    """
    targets = _configured_optional_apis(config)
    if not targets:
        return CategoryResult(
            category="external_apis",
            status=CheckStatus.SKIPPED,
            checks=[
                CheckResult(
                    name="external_apis",
                    status=CheckStatus.SKIPPED,
                    message="No optional external API credentials detected",
                )
            ],
            message="(config-gated)",
        )

    loop = asyncio.get_running_loop()
    tasks = [
        loop.run_in_executor(None, _check_api_reachability, name, url) for name, url in targets
    ]
    checks = list(await asyncio.gather(*tasks))

    return CategoryResult(
        category="external_apis",
        status=aggregate_status([c.status for c in checks]),
        checks=checks,
        message="(config-gated optional)",
    )
