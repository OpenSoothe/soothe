"""Shared types and utilities for SootheRunner."""


def generate_thread_id() -> str:
    """Generate a UUID7 thread ID for time-ordered identifiers.

    Uses uuid7 for consistent ID format across loop_id and thread_id.
    """
    from uuid_utils import uuid7

    return str(uuid7())
