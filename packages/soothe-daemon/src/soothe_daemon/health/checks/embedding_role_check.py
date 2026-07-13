"""Embedding router role health check."""

from __future__ import annotations

from soothe.config import SootheConfig

from soothe_daemon.health.formatters import aggregate_status
from soothe_daemon.health.models import CategoryResult, CheckResult, CheckStatus


async def check_embedding_role(config: SootheConfig | None = None) -> CategoryResult:
    """Verify the daemon has a dedicated ``embedding`` router role configured.

    MemU and vector stores resolve the ``embedding`` router role by default.
    Skillify defaults to ``embedding`` but can override via ``skillify.model_role``.
    When the ``embedding`` role is unset, Soothe falls back to the default chat
    model — which is unsuitable for embeddings.

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
    skillify_model_role = getattr(getattr(config, "skillify", None), "model_role", "embedding")
    skillify_resolved = config.resolve_model(skillify_model_role)

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
                    "skillify_model_role": skillify_model_role,
                    "skillify_resolved": skillify_resolved,
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
                    "skillify_model_role": skillify_model_role,
                    "skillify_resolved": skillify_resolved,
                    "embedding_dims": config.embedding_dims,
                },
            )
        ]

    return CategoryResult(
        category="models",
        status=aggregate_status([c.status for c in checks]),
        checks=checks,
    )
