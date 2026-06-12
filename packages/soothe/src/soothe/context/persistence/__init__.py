"""Persistence backends for the Context Engine (RFC-624)."""

from soothe.context.persistence.base import ContextPersistenceProtocol
from soothe.context.persistence.in_memory import InMemoryContextPersistence

__all__ = [
    "ContextPersistenceProtocol",
    "InMemoryContextPersistence",
]

try:
    from soothe.context.persistence.file_backend import FileContextPersistence  # noqa: F401
except ImportError:
    pass
else:
    __all__.append("FileContextPersistence")
