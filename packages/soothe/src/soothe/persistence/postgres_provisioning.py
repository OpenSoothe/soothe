"""Host alias for shared PostgreSQL provisioning helpers.

Canonical logic lives in :mod:`soothe_nano.persistence.postgres_provisioning`.
The host re-exports it here so host consumers keep the
``soothe.persistence.postgres_provisioning`` import path. The host
``config.env._resolve_env`` and ``foundation.persistence.db_init`` modules are
themselves shims over the nano implementations, so delegating to nano shares
the process-wide provisioning cache and avoids a drifted parallel copy.
"""

from soothe_nano.persistence.postgres_provisioning import (
    ensure_postgres_databases,
    ensure_postgres_databases_async,
    postgres_admin_dsn,
    postgres_target_dsn,
    required_postgres_database_keys,
    reset_provision_cache_for_tests,
    uses_postgresql_persistence,
    validate_database_name,
)

__all__ = [
    "ensure_postgres_databases",
    "ensure_postgres_databases_async",
    "postgres_admin_dsn",
    "postgres_target_dsn",
    "required_postgres_database_keys",
    "reset_provision_cache_for_tests",
    "uses_postgresql_persistence",
    "validate_database_name",
]
