"""Protocol backends health check implementation."""

from soothe.config import SootheConfig
from soothe.core.health.formatters import aggregate_status
from soothe.core.health.models import CategoryResult, CheckResult, CheckStatus


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

    # Context protocol backends
    checks.append(_check_import("soothe.backends.context.vector", "VectorContext"))
    checks.append(_check_import("soothe.backends.context.keyword", "KeywordContext"))

    # Memory protocol backend (MemU)
    checks.append(_check_import("soothe.backends.memory.memu_adapter", "MemU Memory"))

    # Durability protocol backends
    checks.append(_check_import("soothe.backends.durability.json", "JSON Durability"))
    checks.append(_check_import("soothe.backends.durability.rocksdb", "RocksDB Durability"))
    checks.append(_check_import("soothe.backends.durability.postgresql", "PostgreSQL Durability"))

    # Vector store protocol backends
    checks.append(_check_import("soothe.backends.vector_store.in_memory", "InMemory VectorStore"))
    checks.append(_check_import("soothe.backends.vector_store.pgvector", "PGVector"))
    checks.append(_check_import("soothe.backends.vector_store.weaviate", "Weaviate"))

    # Remote agent protocol backend
    checks.append(_check_import("soothe.backends.remote.langgraph", "LangGraph RemoteAgent"))

    overall_status = aggregate_status([check.status for check in checks])

    return CategoryResult(
        category="protocols",
        status=overall_status,
        checks=checks,
    )
