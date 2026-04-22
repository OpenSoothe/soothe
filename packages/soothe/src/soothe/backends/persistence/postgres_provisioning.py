"""PostgreSQL database auto-provisioning utilities.

RFC-612: Auto-provision missing databases on startup.
"""

from __future__ import annotations

import logging

import psycopg

logger = logging.getLogger(__name__)


def provision_database(base_dsn: str, db_name: str) -> None:
    """Auto-provision PostgreSQL database if missing.

    Args:
        base_dsn: Connection string without database name.
        db_name: Database name to create.

    Raises:
        ConfigurationError: If provisioning fails.
    """
    try:
        # Connect to PostgreSQL server (no specific database)
        conn = psycopg.connect(base_dsn)

        try:
            # Check if database exists
            result = conn.execute(
                "SELECT datname FROM pg_database WHERE datname = %s", (db_name,)
            ).fetchone()

            if not result:
                logger.info(f"Creating PostgreSQL database: {db_name}")
                conn.execute(f"CREATE DATABASE {db_name}")
                conn.commit()
                logger.info(f"Database {db_name} created successfully")

        finally:
            conn.close()

    except Exception as e:
        from soothe_sdk.exceptions import ConfigurationError

        logger.error(f"Failed to provision database {db_name}: {e}")
        raise ConfigurationError(
            f"PostgreSQL database provisioning failed: {db_name}\n"
            f"Error: {e}\n"
            f"Ensure PostgreSQL user has CREATEDB privilege"
        )


__all__ = ["provision_database"]
