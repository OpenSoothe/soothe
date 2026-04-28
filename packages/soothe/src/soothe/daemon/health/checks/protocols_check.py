"""Protocol backends health check implementation."""

from soothe.config import SootheConfig
from soothe.daemon.health.formatters import aggregate_status
from soothe.daemon.health.models import CategoryResult, CheckResult, CheckStatus


def _check_import(module_path: str, name: str) -> CheckResult:
    """Check if a module can be imported.

    Args:
        module_path: Full module path to import
        name: Human-readable name for the check

    Returns:
        CheckResult with import status
    """
    try:
        __import__(module_path)
        return CheckResult(
            name=name,
            status=CheckStatus.OK,
            message=f"{name} import successful",
        )
    except ImportError as e:
        return CheckResult(
            name=name,
            status=CheckStatus.ERROR,
            message=f"{name} import failed: {e}",
            details={"module": module_path, "remediation": f"Install required package for {name}"},
        )


async def check_protocols(config: SootheConfig | None = None) -> CategoryResult:  # noqa: ARG001
    """Check protocol backends.

    Verifies that all protocol backend implementations can be imported.

    Args:
        config: SootheConfig instance (not used, all checks are import-only)

    Returns:
        CategoryResult with protocol check results
    """
    checks = []

    # Memory protocol backend (MemU)
    checks.append(_check_import("soothe.backends.memory.memu_adapter", "MemU Memory"))

    # Durability protocol backends
    checks.append(_check_import("soothe.backends.durability.postgresql", "PostgreSQL Durability"))
    checks.append(_check_import("soothe.backends.durability.sqlite", "SQLite Durability"))

    # Vector store protocol backends
    checks.append(_check_import("soothe.backends.vector_store.pgvector", "PGVector"))
    checks.append(_check_import("soothe.backends.vector_store.weaviate", "Weaviate"))
    checks.append(_check_import("soothe.backends.vector_store.sqlite_vec", "sqlite_vec"))

    overall_status = aggregate_status([check.status for check in checks])

    return CategoryResult(
        category="protocols",
        status=overall_status,
        checks=checks,
    )
