"""Shared helpers for psycopg AsyncConnectionPool lifecycle (IG-406)."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from psycopg_pool import AsyncConnectionPool

    from soothe_nano.config import SootheConfig

logger = logging.getLogger(__name__)


def postgres_pool_timing_from_config(
    config: SootheConfig,
    *,
    max_size: int | None = None,
) -> dict[str, Any]:
    """Shared psycopg pool timing options from ``PersistenceConfig`` (caller sets max_size).

    When *max_size* is given, ``min_size`` is capped so psycopg's ``max_size >= min_size`` holds
    (e.g. small ``checkpoints_pool_size`` in tests or worker_pool tuning).
    """
    p = config.persistence
    min_size = p.postgres_pool_min_size
    if max_size is not None:
        min_size = min(min_size, max_size)
    return {
        "min_size": min_size,
        "timeout": float(p.postgres_pool_acquire_timeout_seconds),
        "max_idle": float(p.postgres_pool_max_idle_seconds),
        "max_lifetime": float(p.postgres_pool_max_lifetime_seconds),
        "kwargs": {
            "autocommit": True,
            "prepare_threshold": 0,
        },
    }


def apply_row_factory(pool_kwargs: dict[str, Any]) -> dict[str, Any]:
    """Attach ``dict_row`` factory for checkpoint-style queries."""
    from psycopg.rows import dict_row

    inner = dict(pool_kwargs.get("kwargs") or {})
    inner["row_factory"] = dict_row
    out = dict(pool_kwargs)
    out["kwargs"] = inner
    return out


async def ensure_async_pool_open(pool: AsyncConnectionPool | None) -> None:
    """Open a psycopg ``AsyncConnectionPool`` created with ``open=False``.

    Idempotent when the pool is already open. No-op for non-pool stand-ins (tests).
    Skips closed pools (caller must rebind).
    """
    if pool is None:
        return
    if getattr(pool, "closed", False):
        return
    open_fn = getattr(pool, "open", None)
    if not callable(open_fn):
        return
    try:
        await open_fn()
    except Exception as exc:
        text = str(exc).lower()
        if "already open" in text:
            return
        raise


async def release_idle_pool_connections(
    pool: AsyncConnectionPool | None,
    *,
    label: str,
) -> None:
    """Return dead connections and shrink idle slots (psycopg ``Pool.check``)."""
    if pool is None:
        return
    try:
        if getattr(pool, "closed", False):
            return
        await pool.check()
        stats = pool.get_stats()
        logger.debug(
            "%s pool after idle release: pool_size=%s pool_available=%s requests_waiting=%s",
            label,
            stats.get("pool_size"),
            stats.get("pool_available"),
            stats.get("requests_waiting"),
        )
    except Exception:
        logger.debug("%s pool idle release failed", label, exc_info=True)


def _is_cross_loop_close_error(exc: BaseException) -> bool:
    """Return True when ``pool.close()`` was invoked from the wrong event loop."""
    if not isinstance(exc, ValueError):
        return False
    text = str(exc).lower()
    return "different loop" in text or "belongs to a different loop" in text


async def close_async_pool(pool: AsyncConnectionPool | None, *, label: str) -> None:
    """Close a pool if present and not already closed."""
    if pool is None:
        return
    try:
        if getattr(pool, "closed", False):
            return
        await pool.close()
        logger.info("Closed %s PostgreSQL connection pool", label)
    except ValueError as exc:
        if _is_cross_loop_close_error(exc):
            logger.warning(
                "Skipped closing %s pool from a different event loop; abandoning stale pool",
                label,
            )
            return
        logger.debug("Failed to close %s pool", label, exc_info=True)
    except Exception:
        logger.debug("Failed to close %s pool", label, exc_info=True)


__all__ = [
    "apply_row_factory",
    "close_async_pool",
    "ensure_async_pool_open",
    "postgres_pool_timing_from_config",
    "release_idle_pool_connections",
]
