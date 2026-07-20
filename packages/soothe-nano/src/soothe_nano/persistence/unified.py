"""Unified persistence configuration (AGENTS.md §10).

Ensures daemon-owned durable stores follow ``persistence.default_backend``
as a single mode — postgresql XOR sqlite — never mixed.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from soothe_nano.config import SootheConfig

logger = logging.getLogger(__name__)


def configure_unified_persistence(config: SootheConfig) -> None:
    """Configure process-wide stores that must track ``default_backend``.

    Call after PostgreSQL databases are provisioned (when applicable).
    """
    _validate_no_mixed_overrides(config)
    _warn_vector_store_mismatch(config)

    from soothe_nano.backends.persistence.display_store import configure_display_card_store

    configure_display_card_store(config)
    logger.info(
        "Unified persistence configured: default_backend=%s",
        config.persistence.default_backend,
    )


def _validate_no_mixed_overrides(config: SootheConfig) -> None:
    """Reject durability overrides that disagree with default_backend."""
    default = config.persistence.default_backend
    durability = config.agent.protocols.durability
    for label, value in (
        ("durability.backend", durability.backend),
        ("durability.checkpointer", durability.checkpointer),
    ):
        if value in ("default", default):
            continue
        msg = (
            f"Mixed persistence mode forbidden: persistence.default_backend={default!r} "
            f"but agent.protocols.{label}={value!r}. "
            f"Use 'default' (or the same backend) for a unified process."
        )
        raise ValueError(msg)


def _warn_vector_store_mismatch(config: SootheConfig) -> None:
    """Log a warning when vector routing fights the persistence mode."""
    default = config.persistence.default_backend
    router = (config.vector_store_router.default or "").lower()
    if default == "postgresql" and "sqlite" in router:
        logger.warning(
            "persistence.default_backend=postgresql but vector_store_router.default=%r "
            "looks like sqlite_vec; deploy configs should use pgvector for a unified mode",
            config.vector_store_router.default,
        )
    if default == "sqlite" and "pgvector" in router:
        logger.warning(
            "persistence.default_backend=sqlite but vector_store_router.default=%r "
            "looks like pgvector; prefer sqlite_vec for a unified mode",
            config.vector_store_router.default,
        )


__all__ = ["configure_unified_persistence"]
