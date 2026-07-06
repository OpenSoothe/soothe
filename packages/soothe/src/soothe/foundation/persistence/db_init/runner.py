"""Apply idempotent SQL init scripts and versioned migrations on PostgreSQL.

Each logical database may provide:

- ``init.sql`` — idempotent bootstrap (re-run on every pool open)
- ``NNN_snake_name.sql`` — incremental migrations recorded in
  ``soothe_schema_migrations`` (applied once, in version order)

``initialize_database()`` runs ``init.sql`` first, then pending versioned scripts.
"""

from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from psycopg_pool import AsyncConnectionPool

logger = logging.getLogger(__name__)

_BLOCK_COMMENT = re.compile(r"/\*.*?\*/", re.DOTALL)
_MIGRATION_FILENAME = re.compile(r"^(\d{3})_(.+)\.sql$")
_INIT_FILENAME = "init.sql"


@dataclass(frozen=True, slots=True)
class MigrationScript:
    """One versioned SQL file on disk."""

    version: str
    name: str
    path: Path
    sql: str


@dataclass(frozen=True, slots=True)
class DatabaseSchemaResult:
    """Outcome of ``initialize_database``."""

    init_applied: bool
    migrations_applied: list[str] = field(default_factory=list)


def database_sql_root() -> Path:
    """Directory containing per-database SQL script folders."""
    return Path(__file__).resolve().parent.parent / "sql"


def split_sql_statements(sql: str) -> list[str]:
    """Split an SQL script into statements (one per psycopg ``execute()`` call).

    Psycopg rejects multiple commands in a single prepared statement.

    Args:
        sql: Raw SQL file contents.

    Returns:
        Non-empty statements in file order.
    """
    without_blocks = _BLOCK_COMMENT.sub("", sql)
    lines: list[str] = []
    for line in without_blocks.splitlines():
        if "--" in line:
            line = line.split("--", 1)[0]
        lines.append(line)
    merged = "\n".join(lines)
    return [part.strip() for part in merged.split(";") if part.strip()]


def init_script_path(database: str, *, sql_root: Path | None = None) -> Path:
    """Return the init script path for a logical PostgreSQL database name."""
    return (sql_root or database_sql_root()) / database / _INIT_FILENAME


def load_init_script(database: str, *, sql_root: Path | None = None) -> str | None:
    """Load ``init.sql`` for ``database`` if present."""
    path = init_script_path(database, sql_root=sql_root)
    if not path.is_file():
        return None
    sql = path.read_text(encoding="utf-8").strip()
    if not sql:
        msg = f"Database init script is empty: {path}"
        raise ValueError(msg)
    return sql


def discover_versioned_scripts(
    database: str, *, sql_root: Path | None = None
) -> list[MigrationScript]:
    """Discover versioned migration scripts for a database, sorted by version.

    Args:
        database: Logical database name (e.g. ``soothe_checkpoints``).
        sql_root: Override script root (for tests).

    Returns:
        Sorted list of migration scripts (excludes ``init.sql``).

    Raises:
        FileNotFoundError: If the database script directory is missing.
        ValueError: If filenames do not match ``NNN_name.sql``.
    """
    root = sql_root or database_sql_root()
    script_dir = root / database
    if not script_dir.is_dir():
        msg = f"SQL script directory not found: {script_dir}"
        raise FileNotFoundError(msg)

    scripts: list[MigrationScript] = []
    for path in sorted(script_dir.glob("*.sql")):
        if path.name == _INIT_FILENAME:
            continue
        match = _MIGRATION_FILENAME.match(path.name)
        if not match:
            msg = f"Invalid migration filename (expected NNN_name.sql or init.sql): {path.name}"
            raise ValueError(msg)
        version, name = match.groups()
        sql = path.read_text(encoding="utf-8").strip()
        if not sql:
            msg = f"Migration script is empty: {path}"
            raise ValueError(msg)
        scripts.append(
            MigrationScript(
                version=version,
                name=name,
                path=path,
                sql=sql,
            )
        )
    return scripts


def _advisory_lock_key(database: str) -> int:
    """Stable 63-bit advisory lock id per logical database."""
    digest = hashlib.sha256(database.encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big") & 0x7FFF_FFFF_FFFF_FFFF


async def _execute_statements_async(conn: object, statements: list[str]) -> None:
    async with conn.cursor() as cur:  # type: ignore[union-attr]
        for statement in statements:
            await cur.execute(statement)


def _execute_statements_sync(conn: object, statements: list[str]) -> None:
    with conn.cursor() as cur:  # type: ignore[union-attr]
        for statement in statements:
            cur.execute(statement)


async def run_database_init(
    pool: AsyncConnectionPool,
    database: str,
    *,
    sql_root: Path | None = None,
    conn: object | None = None,
) -> bool:
    """Run ``init.sql`` for ``database`` (idempotent bootstrap only)."""
    sql = load_init_script(database, sql_root=sql_root)
    if sql is None:
        logger.debug("No PostgreSQL init script for database %s", database)
        return False

    statements = split_sql_statements(sql)
    if conn is not None:
        await _execute_statements_async(conn, statements)
    else:
        async with pool.connection() as owned:
            await _execute_statements_async(owned, statements)
    logger.debug("PostgreSQL init.sql applied for database %s", database)
    return True


def run_database_init_sync(
    dsn: str,
    database: str,
    *,
    sql_root: Path | None = None,
    conn: object | None = None,
) -> bool:
    """Run ``init.sql`` synchronously (bootstrap only)."""
    sql = load_init_script(database, sql_root=sql_root)
    if sql is None:
        logger.debug("No PostgreSQL init script for database %s", database)
        return False

    statements = split_sql_statements(sql)
    if conn is not None:
        _execute_statements_sync(conn, statements)
    else:
        try:
            import psycopg
        except ImportError as exc:
            msg = "psycopg is required for PostgreSQL schema init"
            raise ImportError(msg) from exc
        with psycopg.connect(dsn, autocommit=True) as owned:
            _execute_statements_sync(owned, statements)
    logger.info("PostgreSQL init.sql applied for database %s", database)
    return True


async def _fetch_applied_versions_on_conn(conn: object) -> set[str]:
    async with conn.cursor() as cur:  # type: ignore[union-attr]
        await cur.execute(
            """
            SELECT version
            FROM soothe_schema_migrations
            ORDER BY version
            """
        )
        rows = await cur.fetchall()
    return {row["version"] for row in rows}


def _fetch_applied_versions_sync(conn: object) -> set[str]:
    with conn.cursor() as cur:  # type: ignore[union-attr]
        cur.execute(
            """
            SELECT version
            FROM soothe_schema_migrations
            ORDER BY version
            """
        )
        rows = cur.fetchall()
    return {row["version"] for row in rows}  # type: ignore[index]


async def _apply_versioned_script_on_conn(conn: object, script: MigrationScript) -> None:
    await conn.set_autocommit(False)  # type: ignore[union-attr]
    try:
        async with conn.transaction():  # type: ignore[union-attr]
            await _execute_statements_async(conn, split_sql_statements(script.sql))
            async with conn.cursor() as cur:  # type: ignore[union-attr]
                await cur.execute(
                    """
                    INSERT INTO soothe_schema_migrations (version, name)
                    VALUES (%s, %s)
                    """,
                    (script.version, script.name),
                )
    finally:
        await conn.set_autocommit(True)  # type: ignore[union-attr]


async def run_database_migrations(
    pool: AsyncConnectionPool,
    database: str,
    *,
    sql_root: Path | None = None,
    conn: object | None = None,
) -> list[str]:
    """Apply pending versioned migrations for ``database``."""
    try:
        scripts = discover_versioned_scripts(database, sql_root=sql_root)
    except FileNotFoundError:
        return []

    if not scripts:
        return []

    async def _run_on_conn(active_conn: object) -> list[str]:
        try:
            applied = await _fetch_applied_versions_on_conn(active_conn)
        except Exception as exc:
            if "soothe_schema_migrations" not in str(exc).lower():
                raise
            logger.debug(
                "Migration ledger not readable yet for %s (%s); applying from scratch",
                database,
                exc,
            )
            applied = set()

        applied_versions: list[str] = []
        for script in scripts:
            if script.version in applied:
                continue
            logger.info(
                "Applying SQL migration %s (%s) on database %s",
                script.version,
                script.name,
                database,
            )
            await _apply_versioned_script_on_conn(active_conn, script)
            applied.add(script.version)
            applied_versions.append(script.version)

        if applied_versions:
            logger.info(
                "Database %s migrations applied: %s",
                database,
                ", ".join(applied_versions),
            )
        return applied_versions

    if conn is not None:
        return await _run_on_conn(conn)

    async with pool.connection() as owned:
        return await _run_on_conn(owned)


def _apply_versioned_script_sync(conn: object, script: MigrationScript) -> None:
    with conn.transaction():  # type: ignore[union-attr]
        _execute_statements_sync(conn, split_sql_statements(script.sql))
        with conn.cursor() as cur:  # type: ignore[union-attr]
            cur.execute(
                """
                INSERT INTO soothe_schema_migrations (version, name)
                VALUES (%s, %s)
                """,
                (script.version, script.name),
            )


def run_database_migrations_sync(
    dsn: str,
    database: str,
    *,
    sql_root: Path | None = None,
    conn: object | None = None,
) -> list[str]:
    """Apply pending versioned migrations synchronously."""
    try:
        scripts = discover_versioned_scripts(database, sql_root=sql_root)
    except FileNotFoundError:
        return []

    if not scripts:
        return []

    try:
        import psycopg
    except ImportError as exc:
        msg = "psycopg is required for PostgreSQL schema migrations"
        raise ImportError(msg) from exc

    def _run_on_conn(active_conn: object) -> list[str]:
        try:
            applied = _fetch_applied_versions_sync(active_conn)
        except Exception as exc:
            if "soothe_schema_migrations" not in str(exc).lower():
                raise
            applied = set()

        applied_versions: list[str] = []
        for script in scripts:
            if script.version in applied:
                continue
            logger.info(
                "Applying SQL migration %s (%s) on database %s",
                script.version,
                script.name,
                database,
            )
            _apply_versioned_script_sync(active_conn, script)
            applied.add(script.version)
            applied_versions.append(script.version)

        if applied_versions:
            logger.info(
                "Database %s migrations applied: %s",
                database,
                ", ".join(applied_versions),
            )
        return applied_versions

    if conn is not None:
        return _run_on_conn(conn)

    with psycopg.connect(dsn, autocommit=False) as owned:
        applied_versions = _run_on_conn(owned)
        owned.commit()
        return applied_versions


async def initialize_database(
    pool: AsyncConnectionPool,
    database: str,
    *,
    sql_root: Path | None = None,
) -> DatabaseSchemaResult:
    """Run ``init.sql`` then pending versioned migrations under an advisory lock."""
    lock_key = _advisory_lock_key(database)

    async with pool.connection() as conn:
        await conn.set_autocommit(True)
        async with conn.cursor() as cur:
            await cur.execute("SELECT pg_advisory_lock(%s)", (lock_key,))
        try:
            init_applied = await run_database_init(pool, database, sql_root=sql_root, conn=conn)
            migrations_applied = await run_database_migrations(
                pool, database, sql_root=sql_root, conn=conn
            )
        finally:
            async with conn.cursor() as cur:
                await cur.execute("SELECT pg_advisory_unlock(%s)", (lock_key,))

    return DatabaseSchemaResult(
        init_applied=init_applied,
        migrations_applied=migrations_applied,
    )


def initialize_database_sync(
    dsn: str,
    database: str,
    *,
    sql_root: Path | None = None,
) -> DatabaseSchemaResult:
    """Run ``init.sql`` then pending versioned migrations synchronously."""
    try:
        import psycopg
    except ImportError as exc:
        msg = "psycopg is required for PostgreSQL schema initialization"
        raise ImportError(msg) from exc

    lock_key = _advisory_lock_key(database)
    init_applied = False
    migrations_applied: list[str] = []

    try:
        with psycopg.connect(dsn, autocommit=True) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT pg_advisory_lock(%s)", (lock_key,))
            try:
                init_applied = run_database_init_sync(dsn, database, sql_root=sql_root, conn=conn)
                migrations_applied = run_database_migrations_sync(
                    dsn, database, sql_root=sql_root, conn=conn
                )
            finally:
                with conn.cursor() as cur:
                    cur.execute("SELECT pg_advisory_unlock(%s)", (lock_key,))
    except Exception as exc:
        msg = f"Failed to initialize PostgreSQL schema for {database}: {exc}"
        raise RuntimeError(msg) from exc

    if init_applied or migrations_applied:
        logger.info(
            "PostgreSQL schema ready for database %s (init=%s, migrations=%s)",
            database,
            init_applied,
            ", ".join(migrations_applied) if migrations_applied else "none",
        )

    return DatabaseSchemaResult(
        init_applied=init_applied,
        migrations_applied=migrations_applied,
    )


__all__ = [
    "DatabaseSchemaResult",
    "MigrationScript",
    "database_sql_root",
    "discover_versioned_scripts",
    "init_script_path",
    "initialize_database",
    "initialize_database_sync",
    "load_init_script",
    "run_database_init",
    "run_database_init_sync",
    "run_database_migrations",
    "run_database_migrations_sync",
    "split_sql_statements",
]
