"""Configurable timeouts for integration tests.

All timeouts can be overridden via environment variables for CI optimization.
Shorter defaults are used when SOOTHE_TEST_FAST=1 is set.

Environment Variables:
    SOOTHE_TEST_FAST: Set to "1" to use fast (shorter) timeouts for CI
    SOOTHE_TEST_TIMEOUT_DEFAULT: Default timeout for most operations (default: 30.0s, fast: 5.0s)
    SOOTHE_TEST_TIMEOUT_LLM: Timeout for LLM-backed operations (default: 180.0s, fast: 30.0s)
    SOOTHE_TEST_TIMEOUT_SUBSCRIBE: Timeout for subscribe operations (default: 30.0s, fast: 5.0s)
    SOOTHE_TEST_TIMEOUT_DELETE: Timeout for loop_delete operations (default: 120.0s, fast: 15.0s)
    SOOTHE_TEST_TIMEOUT_RAY: Timeout for Ray runner operations (default: 15.0s, fast: 5.0s)
    SOOTHE_TEST_TIMEOUT_POSTGRES: Timeout for PostgreSQL pool operations (default: 5.0s, fast: 2.0s)
    SOOTHE_TEST_TIMEOUT_CONFIG_RELOAD: Timeout for config reload operations (default: 5.0s, fast: 2.0s)
    SOOTHE_TEST_TIMEOUT_EVENT_WAIT: Timeout for waiting for events (default: 2.0s, fast: 0.5s)
    SOOTHE_TEST_TIMEOUT_EVENT_POLL: Timeout for polling events in loops (default: 0.5s, fast: 0.1s)
"""

from __future__ import annotations

import os
from functools import lru_cache


def _is_fast_mode() -> bool:
    """Check if fast test mode is enabled via environment variable."""
    return os.getenv("SOOTHE_TEST_FAST", "").strip() in ("1", "true", "yes")


@lru_cache(maxsize=1)
def _get_timeout_overrides() -> dict[str, float]:
    """Get all timeout overrides from environment variables."""
    return {}


def get_timeout(name: str, default: float, fast_default: float | None = None) -> float:
    """Get a configurable timeout value.

    Args:
        name: Environment variable name (without SOOTHE_TEST_TIMEOUT_ prefix)
        default: Default timeout in seconds
        fast_default: Default timeout in fast mode (defaults to default/4)

    Returns:
        Timeout value in seconds

    """
    env_name = f"SOOTHE_TEST_TIMEOUT_{name}"
    env_value = os.getenv(env_name, "").strip()

    if env_value:
        try:
            return max(0.1, float(env_value))
        except ValueError:
            pass

    if _is_fast_mode():
        return fast_default if fast_default is not None else max(0.5, default / 4)

    return default


# Pre-defined timeout getters for common operations
def timeout_default() -> float:
    """Default timeout for most operations."""
    return get_timeout("DEFAULT", 30.0, 5.0)


def timeout_llm() -> float:
    """Timeout for LLM-backed operations."""
    return get_timeout("LLM", 180.0, 30.0)


def timeout_subscribe() -> float:
    """Timeout for subscribe operations."""
    return get_timeout("SUBSCRIBE", 30.0, 5.0)


def timeout_delete() -> float:
    """Timeout for loop_delete operations."""
    return get_timeout("DELETE", 120.0, 15.0)


def timeout_ray() -> float:
    """Timeout for Ray runner operations."""
    return get_timeout("RAY", 15.0, 5.0)


def timeout_postgres() -> float:
    """Timeout for PostgreSQL pool operations."""
    return get_timeout("POSTGRES", 5.0, 2.0)


def timeout_config_reload() -> float:
    """Timeout for config reload operations."""
    return get_timeout("CONFIG_RELOAD", 5.0, 2.0)


def timeout_event_wait() -> float:
    """Timeout for waiting for events."""
    return get_timeout("EVENT_WAIT", 2.0, 0.5)


def timeout_event_poll() -> float:
    """Timeout for polling events in loops."""
    return get_timeout("EVENT_POLL", 0.5, 0.1)


def timeout_unit_wait() -> float:
    """Timeout for unit test async waits."""
    return get_timeout("UNIT_WAIT", 1.0, 0.25)


def timeout_ack() -> float:
    """Timeout for connection ack operations."""
    return get_timeout("ACK", 5.0, 1.0)


# Legacy compatibility - maps to the existing integration_llm_idle_timeout
def integration_llm_idle_timeout() -> float:
    """Seconds to wait for daemon idle after an LLM-backed turn (override via env).

    This is the legacy function preserved for backward compatibility.
    """
    raw = os.getenv("SOOTHE_INTEGRATION_LLM_IDLE_TIMEOUT", "").strip()
    if raw:
        try:
            return max(10.0, float(raw))
        except ValueError:
            pass
    return timeout_llm()
