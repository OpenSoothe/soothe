"""LLM provider connectivity health check implementation."""

import asyncio
from typing import Any

from soothe.config import SootheConfig

from soothe_daemon.daemon.health.formatters import aggregate_status
from soothe_daemon.daemon.health.models import CategoryResult, CheckResult, CheckStatus


async def _check_provider(provider_name: str, config: SootheConfig | None) -> CheckResult:
    """Check a specific LLM provider.

    Args:
        provider_name: Name of the provider to check
        config: SootheConfig instance

    Returns:
        CheckResult for the provider
    """
    if config is None:
        return CheckResult(
            name=provider_name,
            status=CheckStatus.SKIPPED,
            message="Skipped (no config loaded)",
        )

    # Find provider config
    provider_config = None
    for p in config.providers:
        if p.name == provider_name:
            provider_config = p
            break

    if not provider_config:
        return CheckResult(
            name=provider_name,
            status=CheckStatus.INFO,
            message=f"{provider_name} not configured",
        )

    # Check API key
    if not provider_config.api_key:
        return CheckResult(
            name=provider_name,
            status=CheckStatus.WARNING,
            message=f"{provider_name} API key not set",
            details={"remediation": f"Set {provider_name.upper()}_API_KEY or configure in config"},
        )

    # Try to create a chat model and make a test call
    try:
        # Create a minimal test model
        model = config.create_chat_model(provider_name)

        # IG-143: Add metadata for tracing
        from soothe_daemon.core.middleware._utils import create_llm_call_metadata

        # Try a minimal test call with timeout
        # Use asyncio.wait_for to enforce timeout
        async def test_call() -> Any:
            from langchain_core.messages import HumanMessage

            return await model.ainvoke(
                [HumanMessage(content="test")],
                config={
                    "metadata": create_llm_call_metadata(
                        purpose="health_check",
                        component="daemon.health.providers",
                        phase="startup",
                        provider=provider_name,
                    )
                },
            )

        try:
            await asyncio.wait_for(test_call(), timeout=5.0)

            return CheckResult(
                name=provider_name,
                status=CheckStatus.OK,
                message=f"{provider_name} API key valid, models accessible",
            )
        except TimeoutError:
            return CheckResult(
                name=provider_name,
                status=CheckStatus.WARNING,
                message=f"{provider_name} API call timeout (5s)",
                details={"impact": "Provider may be slow or unreachable"},
            )

    except Exception as e:
        error_msg = str(e)
        # Categorize common errors
        if "api_key" in error_msg.lower() or "unauthorized" in error_msg.lower():
            return CheckResult(
                name=provider_name,
                status=CheckStatus.ERROR,
                message=f"{provider_name} API key invalid",
                details={"error": error_msg, "remediation": "Check API key is correct"},
            )
        if "rate limit" in error_msg.lower():
            return CheckResult(
                name=provider_name,
                status=CheckStatus.WARNING,
                message=f"{provider_name} rate limited",
                details={"error": error_msg},
            )
        return CheckResult(
            name=provider_name,
            status=CheckStatus.ERROR,
            message=f"{provider_name} test call failed: {error_msg}",
            details={"remediation": f"Check {provider_name} service status"},
        )


async def check_providers(config: SootheConfig | None = None) -> CategoryResult:
    """Check LLM provider connectivity.

    Tests each configured provider with a minimal API call to verify
    credentials and connectivity.

    Args:
        config: SootheConfig instance

    Returns:
        CategoryResult with provider check results
    """
    # Check common providers in parallel
    provider_names = ["openai", "anthropic", "google", "ollama"]

    # Run all provider checks in parallel
    tasks = [_check_provider(name, config) for name in provider_names]
    checks = await asyncio.gather(*tasks)

    overall_status = aggregate_status([check.status for check in checks])

    return CategoryResult(
        category="providers",
        status=overall_status,
        checks=list(checks),
    )
