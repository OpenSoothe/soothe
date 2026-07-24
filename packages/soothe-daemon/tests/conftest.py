"""Root conftest for soothe-daemon tests."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Add the soothe-daemon tests directory to the path for imports
# This allows imports like 'from tests.integration.daemon_fixtures import ...' to work
# when running tests from the repository root
_DAEMON_TESTS_DIR = Path(__file__).resolve().parent
if str(_DAEMON_TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(_DAEMON_TESTS_DIR))


@pytest.fixture(autouse=True)
def _close_sqlite_runtime_registry():
    """Session backstop: release every ``SqliteStoreRuntime`` after each test.

    See ``packages/soothe/tests/conftest.py`` for the full rationale.  IG-647's
    process-global ``SqliteRuntimeRegistry`` leaks a Runtime (4 open sqlite3
    connections) per unreleased ``acquire()``; without this backstop the
    suite exhausts file descriptors (``OSError: [Errno 24]``) under the macOS
    default fd limit.
    """
    yield
    try:
        from soothe_nano.persistence.sqlite_runtime import SqliteRuntimeRegistry

        SqliteRuntimeRegistry.close_all_sync()
    except Exception:
        pass
