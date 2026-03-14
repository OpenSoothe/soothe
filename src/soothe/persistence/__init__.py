"""Backward-compatible re-export -- canonical location is ``soothe.backends.persistence``."""

from soothe.backends.persistence import PersistStore, create_persist_store

__all__ = ["PersistStore", "create_persist_store"]
