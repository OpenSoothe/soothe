"""Host checkpointer pool — delegates to nano, bound to the host pool registry.

Canonical logic lives in :mod:`soothe_nano.resolve.shared_checkpointer_pool`.
The host subclass only overrides ``_REGISTRY_CLS`` so the checkpointer singleton
binds to the host :class:`PostgresPoolRegistry` (which opens the host-owned
``checkpoints`` database).
"""

from soothe_nano.resolve.shared_checkpointer_pool import (
    SharedCheckpointerPool as _NanoSharedCheckpointerPool,
)

from soothe.persistence.postgres_pool_registry import PostgresPoolRegistry


class SharedCheckpointerPool(_NanoSharedCheckpointerPool):
    """Host checkpointer pool bound to the host registry (extends nano's)."""

    _REGISTRY_CLS = PostgresPoolRegistry


__all__ = ["SharedCheckpointerPool"]
