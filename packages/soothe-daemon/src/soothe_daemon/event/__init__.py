"""Event infrastructure for the daemon (RFC-0013, IG-258, IG-403, RFC-411).

This submodule provides:
- EventBus: Topic-based pub/sub with lock-free publishing
- EventSizeDistributionCollector: Wire-size histogram monitoring
- loop_event_topic: Topic string utility for loop-scoped routing
- handle_loop_reattach: History reconstruction for client reattachment

Internal API - imported by daemon components, not user-facing.
"""

from soothe_daemon.event.bus import EventBus
from soothe_daemon.event.reattachment import handle_loop_reattach
from soothe_daemon.event.size_stats import EventSizeDistributionCollector
from soothe_daemon.event.topic import loop_event_topic

__all__ = [
    "EventBus",
    "EventSizeDistributionCollector",
    "handle_loop_reattach",
    "loop_event_topic",
]
