"""Persistence layer health check implementation."""

import contextlib
import shutil
from pathlib import Path

from soothe.config import SOOTHE_HOME, SootheConfig

from soothe.daemon.health.formatters import aggregate_status
from soothe.daemon.health.models import CategoryResult, CheckResult, CheckStatus


def _check_postgresql_import() -> CheckResult:
    """Check if PostgreSQL driver is importable."""
    try:
        import psycopg  # noqa: F401

        return CheckResult(
            name="postgresql_import",
            status=CheckStatus.OK,
            message="PostgreSQL driver (psycopg) available",
        )
    except ImportError:
        return CheckResult(
            name="postgresql_import",
            status=CheckStatus.INFO,
            message="PostgreSQL driver not installed (optional)",
            details={"remediation": "Install psycopg for PostgreSQL support"},
        )


def _check_postgresql_connection(config: SootheConfig | None) -> CheckResult:
    """Check PostgreSQL connection if configured."""
    if config is None:
        return CheckResult(
            name="postgresql_connection",
            status=CheckStatus.SKIPPED,
            message="Skipped (no config loaded)",
        )

    # Check if PostgreSQL is configured for any backend
    uses_postgres = False
    dsn = None

    # Check durability backend
    if (
        hasattr(config, "protocols")
        and hasattr(config.protocols, "durability")
        and config.protocols.durability.backend == "postgresql"
    ):
        uses_postgres = True
        with contextlib.suppress(Exception):
            dsn = config.resolve_persistence_postgres_dsn()

    # Check vector stores for PGVector
    if hasattr(config, "vector_stores"):
        for vs in config.vector_stores:
            if vs.provider_type == "pgvector":
                uses_postgres = True
                break

    if not uses_postgres:
        return CheckResult(
            name="postgresql_connection",
            status=CheckStatus.INFO,
            message="PostgreSQL not configured",
        )

    # Try to connect if DSN is available
    if not dsn:
        return CheckResult(
            name="postgresql_connection",
            status=CheckStatus.WARNING,
            message="PostgreSQL configured but DSN not available",
            details={"remediation": "Check persistence.postgres_dsn in config"},
        )

    try:
        import psycopg
        from psycopg.rows import dict_row

        with psycopg.connect(dsn, row_factory=dict_row) as conn, conn.cursor() as cur:
            cur.execute("SELECT version()")
            result = cur.fetchone()

            version = result["version"] if result else "unknown"

            return CheckResult(
                name="postgresql_connection",
                status=CheckStatus.OK,
                message="PostgreSQL connection successful",
                details={"version": version.split(",")[0] if version else "unknown"},
            )

    except ImportError:
        return CheckResult(
            name="postgresql_connection",
            status=CheckStatus.ERROR,
            message="PostgreSQL driver not installed but required by config",
            details={"remediation": "Install psycopg package"},
        )
    except Exception as e:
        return CheckResult(
            name="postgresql_connection",
            status=CheckStatus.ERROR,
            message=f"PostgreSQL connection failed: {e}",
            details={
                "impact": "Durability and vector stores using PostgreSQL unavailable",
                "remediation": "Check PostgreSQL is running and DSN is correct",
            },
        )


def _check_rocksdb_import() -> CheckResult:
    """Check if RocksDB is importable."""
    try:
        import rocksdb  # noqa: F401

        return CheckResult(
            name="rocksdb_import",
            status=CheckStatus.OK,
            message="RocksDB driver available",
        )
    except ImportError:
        return CheckResult(
            name="rocksdb_import",
            status=CheckStatus.INFO,
            message="RocksDB driver not installed (optional)",
            details={"remediation": "Install python-rocksdb for RocksDB durability"},
        )


def _check_filesystem_permissions() -> CheckResult:
    """Check filesystem permissions in SOOTHE_HOME."""
    home = Path(SOOTHE_HOME).expanduser()

    if not home.exists():
        return CheckResult(
            name="filesystem_permissions",
            status=CheckStatus.ERROR,
            message=f"SOOTHE_HOME not found: {home}",
            details={"remediation": "Run 'soothe config init'"},
        )

    # Check write permissions
    test_file = home / ".write_test"
    try:
        test_file.touch()
        test_file.unlink()
    except PermissionError:
        return CheckResult(
            name="filesystem_permissions",
            status=CheckStatus.ERROR,
            message=f"SOOTHE_HOME not writable: {home}",
            details={"remediation": "Fix directory permissions"},
        )

    return CheckResult(
        name="filesystem_permissions",
        status=CheckStatus.OK,
        message="Filesystem permissions OK",
    )


def _check_disk_space() -> CheckResult:
    """Check available disk space."""
    home = Path(SOOTHE_HOME).expanduser()

    if not home.exists():
        return CheckResult(
            name="disk_space",
            status=CheckStatus.SKIPPED,
            message="Skipped (SOOTHE_HOME not found)",
        )

    try:
        usage = shutil.disk_usage(home)
        free_gb = usage.free / (1024**3)
        total_gb = usage.total / (1024**3)
        percent_free = (usage.free / usage.total) * 100

        # Warn if less than 1GB free
        if usage.free < 1024**3:  # 1GB
            return CheckResult(
                name="disk_space",
                status=CheckStatus.WARNING,
                message=f"Low disk space: {free_gb:.1f}GB free ({percent_free:.1f}%)",
                details={"impact": "May cause failures for durability and storage"},
            )

        return CheckResult(
            name="disk_space",
            status=CheckStatus.OK,
            message=f"Disk space OK: {free_gb:.1f}GB free of {total_gb:.1f}GB ({percent_free:.1f}%)",
            details={"free_gb": round(free_gb, 2), "total_gb": round(total_gb, 2)},
        )
    except Exception as e:
        return CheckResult(
            name="disk_space",
            status=CheckStatus.WARNING,
            message=f"Could not check disk space: {e}",
        )


async def check_persistence(config: SootheConfig | None = None) -> CategoryResult:
    """Check persistence layer (PostgreSQL, RocksDB, filesystem).

    Args:
        config: SootheConfig instance

    Returns:
        CategoryResult with persistence check results
    """
    checks = [
        _check_postgresql_import(),
        _check_postgresql_connection(config),
        _check_rocksdb_import(),
        _check_filesystem_permissions(),
        _check_disk_space(),
    ]

    overall_status = aggregate_status([check.status for check in checks])

    return CategoryResult(
        category="persistence",
        status=overall_status,
        checks=checks,
    )
