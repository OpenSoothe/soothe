"""Unit tests for integration port isolation (IG-622)."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.integration.daemon_fixtures import (
    PRODUCTION_DAEMON_WS_PORT,
    alloc_ephemeral_port,
    build_daemon_config,
)


def test_alloc_ephemeral_port_never_returns_production_port() -> None:
    for _ in range(8):
        assert alloc_ephemeral_port() != PRODUCTION_DAEMON_WS_PORT


def test_build_daemon_config_rejects_production_port(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="production daemon port"):
        build_daemon_config(tmp_path, websocket_port=PRODUCTION_DAEMON_WS_PORT)


def test_build_daemon_config_uses_non_production_port(tmp_path: Path) -> None:
    _agent, daemon_cfg = build_daemon_config(tmp_path)
    assert daemon_cfg.transports.websocket.port != PRODUCTION_DAEMON_WS_PORT
