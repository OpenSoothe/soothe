"""Host metadata pool — delegates to nano, bound to the host pool registry."""

from soothe_nano.persistence.shared_metadata_pool import (
    SharedMetadataPool as _NanoSharedMetadataPool,
)

from soothe.persistence.postgres_pool_registry import PostgresPoolRegistry


class SharedMetadataPool(_NanoSharedMetadataPool):
    """Host metadata pool bound to the host registry (extends nano's)."""

    _REGISTRY_CLS = PostgresPoolRegistry


__all__ = ["SharedMetadataPool"]
