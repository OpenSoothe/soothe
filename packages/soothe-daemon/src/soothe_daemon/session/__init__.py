"""Client session infrastructure for the daemon (RFC-0013, IG-408).

This submodule provides:
- ClientSession: Represents a connected client with loop-scoped subscriptions
- ClientSessionManager: Manages client sessions and event delivery
"""

from soothe_daemon.session.manager import ClientSession, ClientSessionManager

__all__ = ["ClientSession", "ClientSessionManager"]
