"""Pytest config for PostgreSQL persistence integration tests.

These tests share long-lived ``AsyncConnectionPool`` singletons whose worker
threads prevent clean event loop teardown between tests. Override the
asyncio loop scope to ``session`` to avoid per-test loop teardown hangs.
"""

import pytest

# Force session-scoped event loop for all tests in this directory.
# Per-test loop teardown hangs on orphaned psycopg_pool worker tasks.
pytestmark = [
    pytest.mark.asyncio(loop_scope="session"),
]
