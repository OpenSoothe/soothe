"""Infrastructure resolution: durability and checkpointer backends."""

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


__all__ = [
    "resolve_checkpointer",
    "resolve_durability",
]
