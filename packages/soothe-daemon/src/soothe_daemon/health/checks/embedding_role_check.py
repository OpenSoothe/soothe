"""Embedding router role health check."""

from __future__ import annotations

from soothe.config import SootheConfig

from soothe_daemon.health.formatters import aggregate_status
from soothe_daemon.health.models import CategoryResult, CheckResult, CheckStatus


async def check_embedding_role(config: SootheConfig | None = None) -> CategoryResult:
    """Verify the daemon has a dedicated embedding profile configured.

    Embedding model + dimensions are sourced from top-level ``embedding_profile``.
    Router profile switching only affects chat/image/ocr roles and must not mutate
    embedding settings.

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

    embedding_profiles = getattr(config, "embedding_profile", None) or []
    resolved = config.resolve_model("embedding")
    skillify_model_role = getattr(getattr(config, "skillify", None), "model_role", "embedding")
    skillify_resolved = config.resolve_model(skillify_model_role)

    if not embedding_profiles:
        checks = [
            CheckResult(
                name="embedding_role_configured",
                status=CheckStatus.WARNING,
                message=(
                    "embedding_profile is not configured; embeddings may drift across restarts"
                ),
                details={
                    "resolved": resolved,
                    "skillify_model_role": skillify_model_role,
                    "skillify_resolved": skillify_resolved,
                    "embedding_dims": config.embedding_dims,
                    "remediation": (
                        "Set top-level embedding_profile with a stable model + dimensions, "
                        "for example model_role=openai:text-embedding-3-small and embedding_dims=1536"
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
                    "embedding_profile_entries": len(embedding_profiles),
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
