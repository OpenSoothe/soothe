"""Retry utilities for PostgreSQL connection resilience.

Provides exponential backoff retry for transient database errors like
AdminShutdown (server restart), OperationalError, and InterfaceError.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Any

logger = logging.getLogger(__name__)


def is_duplicate_schema_error(exc: Exception) -> bool:
    """Return True when concurrent DDL already created the same PostgreSQL object.

    LangGraph ``AsyncPostgresSaver.setup()`` is not safe under parallel calls;
    losers often surface as ``UniqueViolation`` on ``pg_type_typname_nsp_index``.

    Args:
        exc: Exception raised during schema initialization.

    Returns:
        True if the schema likely already exists from a concurrent setup.
    """
    recoverable_classes: tuple[type[BaseException], ...] = ()
    try:
        from psycopg import errors as pg_errors

        recoverable_classes = (
            pg_errors.UniqueViolation,
            pg_errors.DuplicateTable,
            pg_errors.DuplicateObject,
        )
    except Exception:
        recoverable_classes = ()

    if recoverable_classes and isinstance(exc, recoverable_classes):
        return True

    text = str(exc).lower()
    return any(
        needle in text
        for needle in (
            "duplicate key value violates unique constraint",
            "pg_type_typname_nsp_index",
            "already exists",
        )
    )


def is_recoverable_connection_error(exc: Exception) -> bool:
    """Return True for transient PostgreSQL connection failures.

    Detects errors that indicate the PostgreSQL server was restarted,
    shut down, or connection was lost - all recoverable by reconnecting.

    Args:
        exc: Exception to check.

    Returns:
        True if the error is recoverable by reconnecting.
    """
    recoverable_classes: tuple[type[BaseException], ...] = ()
    try:
        import psycopg
        from psycopg import errors as pg_errors

        recoverable_classes = (
            psycopg.OperationalError,
            psycopg.InterfaceError,
            pg_errors.AdminShutdown,
            pg_errors.CrashShutdown,
            pg_errors.ConnectionFailure,
        )
    except Exception:
        recoverable_classes = ()

    if recoverable_classes and isinstance(exc, recoverable_classes):
        return True

    try:
        from psycopg_pool import PoolTimeout

        if isinstance(exc, PoolTimeout):
            return True
    except Exception:
        pass

    # Fallback: check error message for known patterns
    text = str(exc).lower()
    return any(
        needle in text
        for needle in (
            "admin shutdown",
            "terminating connection due to administrator command",
            "connection is closed",
            "connection not open",
            "server closed the connection unexpectedly",
            "connection failure",
            "server is not running",
        )
    )


async def run_with_connection_retry(
    action: str,
    op: Callable[[Any], Awaitable[Any]],
    pool_getter: Callable[[], Awaitable[Any]],
    pool_resetter: Callable[[], Awaitable[None]],
    *,
    max_attempts: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 8.0,
) -> Any:
    """Run operation with exponential backoff retry on connection errors.

    Args:
        action: Action name for logging (e.g., "save_checkpoint").
        op: Async operation that takes pool and returns result.
        pool_getter: Async function to get/ensure pool.
        pool_resetter: Async function to reset pool after error.
        max_attempts: Maximum retry attempts (default: 3).
        base_delay: Initial retry delay in seconds (default: 1.0).
        max_delay: Maximum retry delay cap (default: 8.0).

    Returns:
        Result from successful operation.

    Raises:
        Original exception if all retries exhausted or error is unrecoverable.
    """
    delay = base_delay
    for attempt in range(1, max_attempts + 1):
        pool = await pool_getter()
        try:
            return await op(pool)
        except Exception as exc:
            # Check if this is a recoverable connection error
            if not is_recoverable_connection_error(exc):
                logger.error(
                    "[%s] Unrecoverable error: %s: %s",
                    action,
                    type(exc).__name__,
                    exc,
                )
                raise

            # Last attempt - no more retries
            if attempt >= max_attempts:
                logger.error(
                    "[%s] All %d retries exhausted, last error: %s: %s",
                    action,
                    max_attempts,
                    type(exc).__name__,
                    exc,
                )
                raise

            # Log retry and reset pool
            logger.warning(
                "[%s] Recoverable connection error on attempt %d/%d: %s. "
                "Resetting pool and retrying in %.1fs...",
                action,
                attempt,
                max_attempts,
                type(exc).__name__,
                delay,
            )

            # Reset pool to force new connections
            await pool_resetter()

            # Exponential backoff with cap
            await asyncio.sleep(delay)
            delay = min(delay * 2, max_delay)

    # Should never reach here
    raise RuntimeError(f"Unexpected retry loop exit for {action}")


__all__ = [
    "is_duplicate_schema_error",
    "is_recoverable_connection_error",
    "run_with_connection_retry",
]
