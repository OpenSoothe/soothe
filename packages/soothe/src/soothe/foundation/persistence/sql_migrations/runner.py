"""Apply ordered SQL migration scripts on PostgreSQL pool open / database init.

Scripts live under ``soothe/foundation/persistence/sql/<database>/`` as
``NNN_snake_name.sql`` (three-digit version prefix). Applied versions are
recorded in ``soothe_schema_migrations`` so restarts only run pending scripts.

Simplified for dev-only use: no checksum validation, fresh database init only.
"""

from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from psycopg_pool import AsyncConnectionPool

logger = logging.getLogger(__name__)

_MIGRATION_FILENAME = re.compile(r"^(\d{3})_(.+)\.sql$")
_BLOCK_COMMENT = re.compile(r"/\*.*?\*/", re.DOTALL)
_ADVISORY_LOCK_NAMESPACE = 0x534F_4F54  # "SOOT"


@dataclass(frozen=True, slots=True)
class MigrationScript:
    """One versioned SQL file on disk."""

    version: str
    name: str
    path: Path
    sql: str


def migration_sql_root() -> Path:
    """Directory containing per-database SQL script folders."""
    return Path(__file__).resolve().parent.parent / "sql"


def split_sql_statements(sql: str) -> list[str]:
    """Split a migration script into statements (one per psycopg ``execute()`` call).

    Psycopg rejects multiple commands in a single prepared statement. Migration
    files may contain several DDL statements separated by semicolons.

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


def discover_migration_scripts(
    database: str, *, sql_root: Path | None = None
) -> list[MigrationScript]:
    """Discover migration scripts for a database, sorted by version.

    Args:
        database: Subdirectory name (e.g. ``soothe_checkpoints``).
        sql_root: Override script root (for tests).

    Returns:
        Sorted list of migration scripts.

    Raises:
        FileNotFoundError: If the database script directory is missing.
        ValueError: If filenames do not match ``NNN_name.sql``.
    """
    root = sql_root or migration_sql_root()
    script_dir = root / database
    if not script_dir.is_dir():
        msg = f"SQL migration directory not found: {script_dir}"
        raise FileNotFoundError(msg)

    scripts: list[MigrationScript] = []
    for path in sorted(script_dir.glob("*.sql")):
        match = _MIGRATION_FILENAME.match(path.name)
        if not match:
            msg = f"Invalid migration filename (expected NNN_name.sql): {path.name}"
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


async def _fetch_applied_versions(pool: AsyncConnectionPool) -> set[str]:
    """Fetch already-applied migration versions from tracking table."""
    async with pool.connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                """
                SELECT version
                FROM soothe_schema_migrations
                ORDER BY version
                """
            )
            rows = await cur.fetchall()
    return {row["version"] for row in rows}


async def _apply_script(pool: AsyncConnectionPool, script: MigrationScript) -> None:
    """Apply a single migration script and record it."""
    async with pool.connection() as conn:
        await conn.set_autocommit(False)
        try:
            async with conn.transaction():
                async with conn.cursor() as cur:
                    for statement in split_sql_statements(script.sql):
                        await cur.execute(statement)
                    await cur.execute(
                        """
                        INSERT INTO soothe_schema_migrations (version, name)
                        VALUES (%s, %s)
                        """,
                        (script.version, script.name),
                    )
        finally:
            await conn.set_autocommit(True)


async def run_database_migrations(
    pool: AsyncConnectionPool,
    database: str,
    *,
    sql_root: Path | None = None,
) -> list[str]:
    """Run pending SQL migrations for ``database`` (pool open / init hook).

    Uses a PostgreSQL advisory lock so concurrent pool opens do not apply
    the same migration twice. Already-applied versions are skipped.

    Args:
        pool: Open connection pool connected to the target database.
        database: Script subdirectory name (e.g. ``soothe_checkpoints``).
        sql_root: Optional override for script discovery (tests).

    Returns:
        Versions applied in this call (empty if schema is up to date).

    Raises:
        FileNotFoundError: No script directory for ``database``.
    """
    scripts = discover_migration_scripts(database, sql_root=sql_root)
    if not scripts:
        return []

    lock_key = _advisory_lock_key(database)
    applied_versions: list[str] = []

    async with pool.connection() as conn:
        await conn.set_autocommit(True)
        async with conn.cursor() as cur:
            await cur.execute("SELECT pg_advisory_lock(%s)", (lock_key,))
        try:
            applied: set[str] = set()
            try:
                applied = await _fetch_applied_versions(pool)
            except Exception as exc:
                # First boot: tracking table may not exist until 000 runs.
                if "soothe_schema_migrations" not in str(exc).lower():
                    raise
                logger.debug(
                    "Migration ledger not readable yet for %s (%s); applying from scratch",
                    database,
                    exc,
                )

            for script in scripts:
                if script.version in applied:
                    continue

                logger.info(
                    "Applying SQL migration %s (%s) on database %s",
                    script.version,
                    script.name,
                    database,
                )
                await _apply_script(pool, script)
                applied.add(script.version)
                applied_versions.append(script.version)
        finally:
            async with conn.cursor() as cur:
                await cur.execute("SELECT pg_advisory_unlock(%s)", (lock_key,))

    if applied_versions:
        logger.info(
            "Database %s schema migrations applied: %s",
            database,
            ", ".join(applied_versions),
        )
    else:
        logger.debug("Database %s schema is up to date (%d scripts)", database, len(scripts))

    return applied_versions


__all__ = [
    "MigrationScript",
    "discover_migration_scripts",
    "migration_sql_root",
    "run_database_migrations",
    "split_sql_statements",
]
