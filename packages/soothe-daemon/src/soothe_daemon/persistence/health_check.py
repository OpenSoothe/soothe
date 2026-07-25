"""Persistence layer health check implementation."""

from __future__ import annotations

import shutil
from pathlib import Path

from soothe.config import SOOTHE_HOME, SootheConfig

from soothe_daemon.health.formatters import aggregate_status
from soothe_daemon.health.models import CategoryResult, CheckResult, CheckStatus


def _default_backend(config: SootheConfig | None) -> str:
    if config is None:
        return "sqlite"
    return (config.persistence.default_backend or "sqlite").lower()


def _check_postgresql_import(*, required: bool) -> CheckResult:
    """Check if PostgreSQL driver is importable."""
    import importlib.util

    if importlib.util.find_spec("psycopg") is not None:
        return CheckResult(
            name="postgresql_import",
            status=CheckStatus.OK,
            message="PostgreSQL driver (psycopg) available",
        )
    if required:
        return CheckResult(
            name="postgresql_import",
            status=CheckStatus.ERROR,
            message="PostgreSQL driver not installed but persistence.default_backend=postgresql",
            details={"remediation": "Install psycopg (e.g. pip install 'psycopg[binary]')"},
        )
    return CheckResult(
        name="postgresql_import",
        status=CheckStatus.SKIPPED,
        message="PostgreSQL driver not needed (sqlite backend)",
    )


def _check_postgresql_connection(config: SootheConfig) -> CheckResult:
    """Connect to each configured Postgres database when backend is postgresql."""
    if not config.persistence.postgres_base_dsn:
        return CheckResult(
            name="postgresql_connection",
            status=CheckStatus.ERROR,
            message="persistence.default_backend=postgresql but postgres_base_dsn is unset",
            details={
                "remediation": "Set persistence.postgres_base_dsn (and postgres_databases) in config",
            },
        )

    databases_to_check = list(config.persistence.postgres_databases.keys())
    if not databases_to_check:
        databases_to_check = ["metadata"]

    connection_results: dict[str, dict[str, str]] = {}
    successful: list[str] = []

    for db_key in databases_to_check:
        try:
            dsn = config.resolve_postgres_dsn_for_database(db_key)
            import psycopg
            from psycopg.rows import dict_row

            with psycopg.connect(dsn, row_factory=dict_row) as conn, conn.cursor() as cur:
                cur.execute("SELECT 1 AS ok")
                row = cur.fetchone()
                ok = bool(row and row.get("ok") == 1)
                connection_results[db_key] = {
                    "status": "ok" if ok else "error",
                    "database": dsn.split("/")[-1],
                }
                if ok:
                    successful.append(db_key)
                else:
                    connection_results[db_key]["message"] = "SELECT 1 returned unexpected result"
        except ValueError as e:
            connection_results[db_key] = {"status": "error", "message": str(e)}
        except ImportError:
            return CheckResult(
                name="postgresql_connection",
                status=CheckStatus.ERROR,
                message="PostgreSQL driver not installed but required by config",
                details={"remediation": "Install psycopg package"},
            )
        except Exception as e:
            connection_results[db_key] = {
                "status": "error",
                "message": f"Connection failed: {e}",
            }

    if len(successful) == len(databases_to_check):
        return CheckResult(
            name="postgresql_connection",
            status=CheckStatus.OK,
            message=(
                f"PostgreSQL connection OK ({len(successful)} databases: {', '.join(successful)})"
            ),
            details={"databases": connection_results},
        )

    if successful:
        failed = [db for db in databases_to_check if db not in successful]
        return CheckResult(
            name="postgresql_connection",
            status=CheckStatus.WARNING,
            message=(f"PostgreSQL partial connection: {len(successful)}/{len(databases_to_check)}"),
            details={
                "databases": connection_results,
                "remediation": f"Check database connectivity for: {', '.join(failed)}",
            },
        )

    return CheckResult(
        name="postgresql_connection",
        status=CheckStatus.ERROR,
        message="PostgreSQL configured but all database connections failed",
        details={
            "databases": connection_results,
            "remediation": (
                "Check postgres_base_dsn connectivity and CREATEDB privileges; "
                "Soothe auto-provisions configured databases on startup"
            ),
        },
    )


def _check_sqlite_backend(config: SootheConfig | None) -> CheckResult:
    """Confirm sqlite mode and writable data home."""
    home = Path(SOOTHE_HOME).expanduser()
    details = {"backend": "sqlite", "soothe_home": str(home)}
    if config is not None:
        details["default_backend"] = config.persistence.default_backend
    if not home.exists():
        return CheckResult(
            name="sqlite_backend",
            status=CheckStatus.ERROR,
            message=f"SQLite backend selected but SOOTHE_HOME missing: {home}",
            details={
                **details,
                "remediation": "Run `soothed setup` or create ~/.soothe",
            },
        )
    return CheckResult(
        name="sqlite_backend",
        status=CheckStatus.OK,
        message=f"SQLite persistence backend ready ({home})",
        details=details,
    )


def _check_filesystem_permissions() -> CheckResult:
    """Check filesystem permissions in SOOTHE_HOME."""
    home = Path(SOOTHE_HOME).expanduser()

    if not home.exists():
        return CheckResult(
            name="filesystem_permissions",
            status=CheckStatus.ERROR,
            message=f"SOOTHE_HOME not found: {home}",
            details={
                "remediation": "Create ~/.soothe with config/nano.yml (see docs/user_guide.md)",
            },
        )

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


def _check_postgres_pool_registry(config: SootheConfig) -> CheckResult:
    """Report registry pool stats when the daemon has pre-opened shared pools."""
    try:
        from soothe.persistence.postgres_pool_registry import PostgresPoolRegistry

        registry = PostgresPoolRegistry.try_get_instance()
        if registry is None:
            return CheckResult(
                name="postgres_pool_registry",
                status=CheckStatus.INFO,
                message="Postgres pool registry not initialized (daemon may be offline)",
            )
        stats = registry.pool_stats()
        return CheckResult(
            name="postgres_pool_registry",
            status=CheckStatus.OK,
            message="Postgres pool registry active",
            details={"pools": stats},
        )
    except Exception as exc:
        return CheckResult(
            name="postgres_pool_registry",
            status=CheckStatus.WARNING,
            message=f"Could not read pool registry stats: {exc}",
        )


async def check_persistence(config: SootheConfig | None = None) -> CategoryResult:
    """Check persistence layer gated on ``persistence.default_backend``.

    Args:
        config: SootheConfig instance

    Returns:
        CategoryResult with persistence check results
    """
    backend = _default_backend(config)
    checks: list[CheckResult] = [
        CheckResult(
            name="default_backend",
            status=CheckStatus.OK if config is not None else CheckStatus.INFO,
            message=f"persistence.default_backend={backend}",
            details={"backend": backend},
        )
    ]

    if backend == "postgresql":
        if config is None:
            checks.append(
                CheckResult(
                    name="postgresql_connection",
                    status=CheckStatus.SKIPPED,
                    message="Skipped (no config loaded)",
                )
            )
        else:
            checks.append(_check_postgresql_import(required=True))
            checks.append(_check_postgresql_connection(config))
            checks.append(_check_postgres_pool_registry(config))
    else:
        checks.append(_check_postgresql_import(required=False))
        checks.append(_check_sqlite_backend(config))

    checks.extend(
        [
            _check_filesystem_permissions(),
            _check_disk_space(),
        ]
    )

    return CategoryResult(
        category="persistence",
        status=aggregate_status([check.status for check in checks]),
        checks=checks,
    )
