"""Vector store backends health check implementation."""

from soothe.config import SootheConfig
from soothe.core.health.formatters import aggregate_status
from soothe.core.health.models import CategoryResult, CheckResult, CheckStatus


def _check_inmemory_vectorstore() -> CheckResult:
    """Check in-memory vector store."""
    try:
        from soothe.backends.vector_store.in_memory import InMemoryVectorStore  # noqa: F401

        return CheckResult(
            name="inmemory_vectorstore",
            status=CheckStatus.OK,
            message="In-memory vector store ready",
        )
    except ImportError as e:
        return CheckResult(
            name="inmemory_vectorstore",
            status=CheckStatus.ERROR,
            message=f"In-memory vector store import failed: {e}",
        )


def _check_pgvector(config: SootheConfig | None) -> CheckResult:
    """Check PGVector vector store if configured."""
    # Check if PGVector is configured
    if config is None:
        return CheckResult(
            name="pgvector",
            status=CheckStatus.INFO,
            message="Skipped (no config loaded)",
        )

    uses_pgvector = False
    if hasattr(config, "vector_stores"):
        for vs in config.vector_stores:
            if vs.provider_type == "pgvector":
                uses_pgvector = True
                break

    if not uses_pgvector:
        return CheckResult(
            name="pgvector",
            status=CheckStatus.INFO,
            message="PGVector not configured",
        )

    # Try to import
    try:
        from soothe.backends.vector_store.pgvector import PGVectorStore  # noqa: F401

        return CheckResult(
            name="pgvector",
            status=CheckStatus.OK,
            message="PGVector backend ready",
            details={"note": "Connection depends on PostgreSQL (see persistence checks)"},
        )
    except ImportError as e:
        return CheckResult(
            name="pgvector",
            status=CheckStatus.ERROR,
            message=f"PGVector import failed: {e}",
            details={"remediation": "Install pgvector package"},
        )


def _check_weaviate(config: SootheConfig | None) -> CheckResult:
    """Check Weaviate vector store if configured."""
    # Check if Weaviate is configured
    if config is None:
        return CheckResult(
            name="weaviate",
            status=CheckStatus.INFO,
            message="Skipped (no config loaded)",
        )

    uses_weaviate = False
    if hasattr(config, "vector_stores"):
        for vs in config.vector_stores:
            if vs.provider_type == "weaviate":
                uses_weaviate = True
                break

    if not uses_weaviate:
        return CheckResult(
            name="weaviate",
            status=CheckStatus.INFO,
            message="Weaviate not configured",
        )

    # Try to import
    try:
        from soothe.backends.vector_store.weaviate import WeaviateVectorStore  # noqa: F401

        return CheckResult(
            name="weaviate",
            status=CheckStatus.OK,
            message="Weaviate backend ready",
            details={"note": "Connection requires running Weaviate instance"},
        )
    except ImportError as e:
        return CheckResult(
            name="weaviate",
            status=CheckStatus.ERROR,
            message=f"Weaviate import failed: {e}",
            details={"remediation": "Install weaviate-client package"},
        )


async def check_vector_stores(config: SootheConfig | None = None) -> CategoryResult:
    """Check vector store backends.

    Args:
        config: SootheConfig instance

    Returns:
        CategoryResult with vector store check results
    """
    checks = [
        _check_inmemory_vectorstore(),
        _check_pgvector(config),
        _check_weaviate(config),
    ]

    overall_status = aggregate_status([check.status for check in checks])

    return CategoryResult(
        category="vector_stores",
        status=overall_status,
        checks=checks,
    )
