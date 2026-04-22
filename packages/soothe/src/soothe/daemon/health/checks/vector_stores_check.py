"""Vector store backends health check implementation."""

from soothe.config import SootheConfig
from soothe.daemon.health.formatters import aggregate_status
from soothe.daemon.health.models import CategoryResult, CheckResult, CheckStatus


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


def _check_sqlite_vec(config: SootheConfig | None) -> CheckResult:
    """Check sqlite_vec vector store if configured."""
    if config is None:
        return CheckResult(
            name="sqlite_vec",
            status=CheckStatus.INFO,
            message="Skipped (no config loaded)",
        )

    uses_sqlite_vec = False
    if hasattr(config, "vector_stores"):
        for vs in config.vector_stores:
            if vs.provider_type == "sqlite_vec":
                uses_sqlite_vec = True
                break

    if not uses_sqlite_vec:
        return CheckResult(
            name="sqlite_vec",
            status=CheckStatus.INFO,
            message="sqlite_vec not configured",
        )

    try:
        from soothe.backends.vector_store.sqlite_vec import SQLiteVecStore  # noqa: F401

        return CheckResult(
            name="sqlite_vec",
            status=CheckStatus.OK,
            message="sqlite_vec backend ready",
        )
    except ImportError as e:
        return CheckResult(
            name="sqlite_vec",
            status=CheckStatus.ERROR,
            message=f"sqlite_vec import failed: {e}",
            details={"remediation": "Install sqlite-vec package"},
        )


async def check_vector_stores(config: SootheConfig | None = None) -> CategoryResult:
    """Check vector store backends.

    Args:
        config: SootheConfig instance

    Returns:
        CategoryResult with vector store check results
    """
    checks = [
        _check_pgvector(config),
        _check_weaviate(config),
        _check_sqlite_vec(config),
    ]

    overall_status = aggregate_status([check.status for check in checks])

    return CategoryResult(
        category="vector_stores",
        status=overall_status,
        checks=checks,
    )
