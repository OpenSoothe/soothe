"""Embedding router role health check."""

from __future__ import annotations

from soothe.config import SootheConfig

from soothe_daemon.health.formatters import aggregate_status
from soothe_daemon.health.models import CategoryResult, CheckResult, CheckStatus


async def check_embedding_role(config: SootheConfig | None = None) -> CategoryResult:
    """Verify the daemon has a dedicated ``embedding`` router role configured.

    Skillify, MemU, and vector stores use ``config.create_embedding_model()``, which
    resolves the ``embedding`` role from router profiles. When unset, Soothe falls
    back to the default chat model — which is unsuitable for embeddings.

    Args:
        config: Agent configuration to inspect.

    Returns:
        CategoryResult for the ``models`` category.
    """
    if config is None:
        checks = [
            CheckResult(
                name="embedding_role_configured",
                status=CheckStatus.SKIPPED,
                message="No agent config loaded",
            )
        ]
        return CategoryResult(
            category="models",
            status=aggregate_status([c.status for c in checks]),
            checks=checks,
        )

    explicit = getattr(config.router, "embedding", None)
    resolved = config.resolve_model("embedding")

    if not explicit:
        checks = [
            CheckResult(
                name="embedding_role_configured",
                status=CheckStatus.WARNING,
                message=(
                    "router.embedding is not set; embeddings resolve to the default chat model"
                ),
                details={
                    "resolved": resolved,
                    "embedding_dims": config.embedding_dims,
                    "remediation": (
                        "Set router_profiles.*.router.embedding to a dedicated embedding model "
                        "(e.g. dashscope:text-embedding-v4 or omlx:nomicai-modernbert-embed-base-bf16)"
                    ),
                },
            )
        ]
    else:
        checks = [
            CheckResult(
                name="embedding_role_configured",
                status=CheckStatus.OK,
                message=f"Embedding role configured ({resolved})",
                details={
                    "embedding_dims": config.embedding_dims,
                },
            )
        ]

    return CategoryResult(
        category="models",
        status=aggregate_status([c.status for c in checks]),
        checks=checks,
    )
