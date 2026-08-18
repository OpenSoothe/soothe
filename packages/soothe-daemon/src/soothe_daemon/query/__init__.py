"""Query execution infrastructure for the daemon.

This submodule provides:
- QueryEngine: Query execution lifecycle, streaming, cancellation
"""

from soothe_daemon.query.engine import QueryEngine

__all__ = ["QueryEngine"]
