"""Event topic utilities for loop-scoped routing."""


def loop_event_topic(loop_id: str) -> str:
    """Return the event-bus topic for loop-scoped delivery."""
    return f"loop:{loop_id}"


__all__ = ["loop_event_topic"]
