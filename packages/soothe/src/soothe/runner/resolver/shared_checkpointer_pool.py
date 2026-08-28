"""Host checkpointer pool — delegates to nano, bound to the host pool registry."""

from soothe_nano.resolve.shared_checkpointer_pool import (
    SharedCheckpointerPool as _NanoSharedCheckpointerPool,
)

from soothe.persistence.postgres_pool_registry import PostgresPoolRegistry


class SharedCheckpointerPool(_NanoSharedCheckpointerPool):
    """Host checkpointer pool bound to the host registry (extends nano's)."""

    _REGISTRY_CLS = PostgresPoolRegistry


__all__ = ["SharedCheckpointerPool"]
