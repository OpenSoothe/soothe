"""Unit tests for split-config composition."""

from __future__ import annotations

import pytest

from soothe.config.composition import CompositionConflictError, compose_host_agent_config
from soothe.config.ownership import OwnershipViolationError


def test_compose_host_agent_config_merges_disjoint_sections() -> None:
    nano_data = {
        "providers": [{"name": "openai", "provider_type": "openai"}],
        "agent": {"runtime": {"recursion_limit": 300}},
    }
    soothe_data = {
        "agent": {"loop": {"max_iterations": 77}, "autopilot": {"enabled": True}},
        "cron": {"max_jobs": 50},
    }

    merged = compose_host_agent_config(nano_data, soothe_data)
    assert merged["providers"][0]["name"] == "openai"
    assert merged["agent"]["runtime"]["recursion_limit"] == 300
    assert merged["agent"]["loop"]["max_iterations"] == 77
    assert merged["cron"]["max_jobs"] == 50


def test_compose_host_agent_config_rejects_bad_nano_ownership() -> None:
    nano_data = {"agent": {"loop": {"max_iterations": 10}}}
    soothe_data = {"cron": {"max_jobs": 10}}

    with pytest.raises(OwnershipViolationError):
        compose_host_agent_config(nano_data, soothe_data)


def test_compose_host_agent_config_rejects_bad_host_ownership() -> None:
    nano_data = {"providers": [{"name": "openai", "provider_type": "openai"}]}
    soothe_data = {"providers": [{"name": "other", "provider_type": "openai"}]}

    with pytest.raises(OwnershipViolationError):
        compose_host_agent_config(nano_data, soothe_data)


def test_compose_host_agent_config_detects_conflict_for_same_leaf() -> None:
    nano_data = {"debug": False}
    soothe_data = {"debug": True}

    with pytest.raises(CompositionConflictError) as exc:
        compose_host_agent_config(nano_data, soothe_data)
    assert "debug" in str(exc.value)
