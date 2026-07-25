"""LLM provider connectivity health check implementation."""

from __future__ import annotations

import asyncio
from typing import Any

from soothe.config import SootheConfig

from soothe_daemon.health.formatters import aggregate_status
from soothe_daemon.health.models import CategoryResult, CheckResult, CheckStatus


def _unresolved_env_ref(value: str | None) -> bool:
    return bool(value and "${" in value)


async def _check_provider_credentials(
    provider_name: str,
    api_key: str | None,
    provider_type: str,
) -> CheckResult:
    """Validate that a configured provider has usable credentials."""
    if _unresolved_env_ref(api_key):
        return CheckResult(
            name=provider_name,
            status=CheckStatus.ERROR,
            message=f"{provider_name}: API key still contains unresolved ${{ENV}} reference",
            details={
                "provider_type": provider_type,
                "remediation": f"Export the env var referenced by {provider_name}.api_key",
            },
        )

    # Local / keyless providers
    if provider_type == "ollama":
        return CheckResult(
            name=provider_name,
            status=CheckStatus.OK,
            message=f"{provider_name}: configured (local/keyless provider_type={provider_type})",
            details={"provider_type": provider_type, "api_key_present": bool(api_key)},
        )

    if not api_key:
        return CheckResult(
            name=provider_name,
            status=CheckStatus.ERROR,
            message=f"{provider_name}: API key not set",
            details={
                "provider_type": provider_type,
                "remediation": (
                    f"Set {provider_name}.api_key in config or the corresponding env var"
                ),
            },
        )

    return CheckResult(
        name=provider_name,
        status=CheckStatus.OK,
        message=f"{provider_name}: credentials present (provider_type={provider_type})",
        details={"provider_type": provider_type, "api_key_present": True},
    )


async def _live_invoke_default(config: SootheConfig) -> CheckResult:
    """Optional live invoke against the default router model."""
    try:
        from langchain_core.messages import HumanMessage
        from soothe_nano.utils.llm.invoke_policy import (
            await_with_llm_call_policy,
            llm_rate_limit_config_from,
        )
        from soothe_nano.utils.llm.observability import create_llm_call_metadata

        model = config.create_chat_model("default")
        llm_config = llm_rate_limit_config_from(config).model_copy(
            update={
                "call_timeout_seconds": 5,
                "call_timeout_max_seconds": 5,
                "max_rate_limit_retries": 1,
                "max_timeout_retries": 0,
            }
        )

        async def test_call() -> Any:
            return await model.ainvoke(
                [HumanMessage(content="ping")],
                config={
                    "metadata": create_llm_call_metadata(
                        purpose="health_check",
                        component="daemon.health.providers",
                        phase="doctor",
                        provider="default",
                    )
                },
            )

        await await_with_llm_call_policy(test_call, config=llm_config)
        return CheckResult(
            name="default_model_live",
            status=CheckStatus.OK,
            message=f"Default model live invoke OK ({config.router.default})",
            details={"default": config.router.default},
        )
    except TimeoutError:
        return CheckResult(
            name="default_model_live",
            status=CheckStatus.WARNING,
            message="Default model live invoke timed out (5s)",
            details={"impact": "Provider may be slow or unreachable"},
        )
    except Exception as exc:
        error_msg = str(exc)
        lower = error_msg.lower()
        if "api_key" in lower or "unauthorized" in lower or "401" in lower:
            return CheckResult(
                name="default_model_live",
                status=CheckStatus.ERROR,
                message="Default model live invoke failed: invalid credentials",
                details={"error": error_msg, "remediation": "Check provider API key"},
            )
        if "rate limit" in lower:
            return CheckResult(
                name="default_model_live",
                status=CheckStatus.WARNING,
                message="Default model live invoke rate limited",
                details={"error": error_msg},
            )
        return CheckResult(
            name="default_model_live",
            status=CheckStatus.ERROR,
            message=f"Default model live invoke failed: {error_msg}",
            details={"remediation": "Check provider endpoint and network"},
        )


async def check_providers(
    config: SootheConfig | None = None,
    *,
    live_llm: bool = False,
) -> CategoryResult:
    """Check configured LLM providers (credentials; optional live invoke).

    Args:
        config: SootheConfig instance.
        live_llm: When True, perform a short invoke against ``router.default``.

    Returns:
        CategoryResult with provider check results.
    """
    if config is None:
        return CategoryResult(
            category="providers",
            status=CheckStatus.SKIPPED,
            checks=[
                CheckResult(
                    name="providers",
                    status=CheckStatus.SKIPPED,
                    message="Skipped (no config loaded)",
                )
            ],
        )

    if not config.providers:
        return CategoryResult(
            category="providers",
            status=CheckStatus.ERROR,
            checks=[
                CheckResult(
                    name="providers",
                    status=CheckStatus.ERROR,
                    message="No LLM providers configured",
                    details={
                        "remediation": "Add providers[] in nano.yml or set OPENAI_API_KEY / ANTHROPIC_API_KEY",
                    },
                )
            ],
        )

    tasks = [
        _check_provider_credentials(p.name, p.api_key, p.provider_type) for p in config.providers
    ]
    checks = list(await asyncio.gather(*tasks))

    if live_llm:
        checks.append(await _live_invoke_default(config))

    return CategoryResult(
        category="providers",
        status=aggregate_status([c.status for c in checks]),
        checks=checks,
    )
