"""Unit tests for split-config ownership validation."""

from __future__ import annotations

import pytest

from soothe.config.ownership import (
    OwnershipViolationError,
    validate_host_file_ownership,
    validate_nano_file_ownership,
)


def test_validate_nano_file_ownership_accepts_nano_owned_keys() -> None:
    data = {
        "providers": [{"name": "openai", "provider_type": "openai"}],
        "agent": {
            "runtime": {"recursion_limit": 200},
            "middleware": {"context_window_limit": 200_000},
        },
    }
    validate_nano_file_ownership(data)


def test_validate_nano_file_ownership_rejects_host_owned_keys() -> None:
    data = {"agent": {"loop": {"max_iterations": 99}}}
    with pytest.raises(OwnershipViolationError) as exc:
        validate_nano_file_ownership(data, source_file="nano.yml")
    assert "agent.loop" in str(exc.value)
    assert "soothe.yml" in str(exc.value)


def test_validate_host_file_ownership_accepts_host_owned_keys() -> None:
    data = {
        "agent": {"loop": {"max_iterations": 88}, "autopilot": {"enabled": True}},
        "cron": {"max_jobs": 99},
    }
    validate_host_file_ownership(data)


def test_validate_host_file_ownership_rejects_nano_owned_keys() -> None:
    data = {"providers": [{"name": "openai", "provider_type": "openai"}]}
    with pytest.raises(OwnershipViolationError) as exc:
        validate_host_file_ownership(data, source_file="soothe.yml")
    assert "providers" in str(exc.value)
    assert "nano.yml" in str(exc.value)


def test_strange_loop_rejects_nano_middleware_keys() -> None:
    from soothe.config.models import StrangeLoopConfig

    with pytest.raises(ValueError, match="agent.middleware"):
        StrangeLoopConfig(tool_timeout={"enabled": False})


def test_strange_loop_rejects_legacy_dispatch_timeout() -> None:
    from soothe.config.models import StrangeLoopConfig

    with pytest.raises(ValueError, match="dispatch_timeout_seconds removed"):
        StrangeLoopConfig(dispatch_timeout_seconds=600)
