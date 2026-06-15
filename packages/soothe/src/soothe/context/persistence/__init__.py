"""Persistence backends for the Context Engine (RFC-624)."""

from soothe.context.persistence.base import ContextPersistenceProtocol

__all__ = [
    "ContextPersistenceProtocol",
]

try:
    from soothe.context.persistence.file_backend import FileContextPersistence  # noqa: F401
except ImportError:
    pass
else:
    __all__.append("FileContextPersistence")

try:
    from soothe.context.persistence.sqlite_backend import SqliteContextPersistence  # noqa: F401
except ImportError:
    pass
else:
    __all__.append("SqliteContextPersistence")

try:
    from soothe.context.persistence.pgsql_backend import PgsqlContextPersistence  # noqa: F401
except ImportError:
    pass
else:
    __all__.append("PgsqlContextPersistence")
