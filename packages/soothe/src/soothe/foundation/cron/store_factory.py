"""Factory for CronJobStore backends (unified persistence rule)."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from soothe.config import SootheConfig

logger = logging.getLogger(__name__)


def create_cron_job_store(config: SootheConfig | None = None, **kwargs: Any) -> Any:
    """Return SQLite or PostgreSQL cron store from ``persistence.default_backend``.

    Args:
        config: Active Soothe config. When None or sqlite, returns ``CronJobStore``.
        **kwargs: Forwarded to ``CronJobStore`` (e.g. ``db_path`` for tests).

    Returns:
        CronJobStore or PostgresCronJobStore with the same async API.
    """
    if config is not None and config.persistence.default_backend == "postgresql":
        from soothe.foundation.cron.store_postgres import PostgresCronJobStore

        dsn = config.resolve_postgres_dsn_for_database("metadata")
        logger.info("Cron job store backend=postgresql db=metadata")
        return PostgresCronJobStore(dsn=dsn)

    from soothe.foundation.cron.store import CronJobStore

    logger.info("Cron job store backend=sqlite")
    return CronJobStore(**kwargs)


__all__ = ["create_cron_job_store"]
