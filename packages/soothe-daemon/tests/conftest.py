"""Root conftest for soothe-daemon tests."""

from __future__ import annotations

import sys
from pathlib import Path

# Add the soothe-daemon tests directory to the path for imports
# This allows imports like 'from tests.integration.daemon_fixtures import ...' to work
# when running tests from the repository root
_DAEMON_TESTS_DIR = Path(__file__).resolve().parent
if str(_DAEMON_TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(_DAEMON_TESTS_DIR))
