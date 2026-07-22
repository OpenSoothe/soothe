"""Infrastructure resolution: durability and checkpointer backends.

Host binds pool classes to the host registry-aware shims; canonical logic
lives in :mod:`soothe_nano.resolve._resolver_infra`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from soothe_nano.resolve import _resolver_infra as _nano_infra

from soothe.persistence.shared_metadata_pool import SharedMetadataPool
from soothe.runner.resolver.shared_checkpointer_pool import SharedCheckpointerPool

if TYPE_CHECKING:
    from langgraph.types import Checkpointer
    from soothe_sdk.protocols.durability import DurabilityProtocol

    from soothe.config import SootheConfig


def resolve_durability(config: SootheConfig) -> DurabilityProtocol:
    """Instantiate DurabilityProtocol using the host metadata pool shim."""
    return _nano_infra.resolve_durability(
        config,
        metadata_pool_cls=SharedMetadataPool,
    )


def resolve_checkpointer(config: SootheConfig) -> tuple[Checkpointer, Any] | Checkpointer:
    """Resolve LangGraph checkpointer using the host checkpointer pool shim."""
    return _nano_infra.resolve_checkpointer(
        config,
        checkpointer_pool_cls=SharedCheckpointerPool,
    )


# Re-export helpers used by tests / callers that imported from this module.
_resolve_sqlite_checkpointer = _nano_infra._resolve_sqlite_checkpointer
_resolve_postgres_checkpointer = _nano_infra._resolve_postgres_checkpointer
_mask_dsn = _nano_infra._mask_dsn

__all__ = [
    "resolve_checkpointer",
    "resolve_durability",
]
