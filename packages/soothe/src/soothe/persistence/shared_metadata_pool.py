"""Host metadata pool — delegates to nano, bound to the host pool registry.

Canonical logic lives in :mod:`soothe_nano.persistence.shared_metadata_pool`.
The host subclass only overrides ``_REGISTRY_CLS`` so the metadata singleton
binds to the host :class:`PostgresPoolRegistry` (which extends nano's with the
host-owned ``checkpoints`` database). Previously this module re-declared the
whole class body, drifting in lockstep with nano.
"""

from soothe_nano.persistence.shared_metadata_pool import (
    SharedMetadataPool as _NanoSharedMetadataPool,
)

from soothe.persistence.postgres_pool_registry import PostgresPoolRegistry


class SharedMetadataPool(_NanoSharedMetadataPool):
    """Host metadata pool bound to the host registry (extends nano's)."""

    _REGISTRY_CLS = PostgresPoolRegistry


__all__ = ["SharedMetadataPool"]
