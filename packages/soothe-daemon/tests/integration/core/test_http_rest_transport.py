"""Integration tests for HTTP REST channel (RFC-620)."""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

import httpx
import pytest

from soothe_daemon.channels.http_rest import HttpRestChannel
from soothe_daemon.config.models import HttpRestConfig


@pytest.mark.asyncio
async def test_http_rest_channel_basic() -> None:
    """Test basic HTTP REST channel lifecycle."""
    config = HttpRestConfig(
        enabled=True,
        host="127.0.0.1",
        port=18770,
        tls_enabled=False,
    )

    manager = MagicMock()
    channel = HttpRestChannel(config, manager=manager)

    await channel.start()
    assert channel.name == "http_rest"

    await channel.stop()


@pytest.mark.asyncio
async def test_http_rest_health_endpoint() -> None:
    """Test HTTP REST health endpoint."""
    config = HttpRestConfig(
        enabled=True,
        host="127.0.0.1",
        port=18771,
        tls_enabled=False,
    )

    manager = MagicMock()
    channel = HttpRestChannel(config, manager=manager)

    await channel.start()

    try:
        await asyncio.sleep(0.5)

        async with httpx.AsyncClient() as client:
            response = await client.get("http://127.0.0.1:18771/api/v1/health")
            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "healthy"
            assert data["transport"] == "http_rest"
    finally:
        await channel.stop()


@pytest.mark.asyncio
async def test_http_rest_status_endpoint() -> None:
    """Test HTTP REST status endpoint."""
    config = HttpRestConfig(
        enabled=True,
        host="127.0.0.1",
        port=18772,
        tls_enabled=False,
    )

    manager = MagicMock()
    channel = HttpRestChannel(config, manager=manager)

    await channel.start()

    try:
        await asyncio.sleep(0.5)

        async with httpx.AsyncClient() as client:
            response = await client.get("http://127.0.0.1:18772/api/v1/status")
            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "running"
            assert data["transport"] == "http_rest"
    finally:
        await channel.stop()


@pytest.mark.asyncio
async def test_http_rest_version_endpoint() -> None:
    """Test HTTP REST version endpoint."""
    config = HttpRestConfig(
        enabled=True,
        host="127.0.0.1",
        port=18773,
        tls_enabled=False,
    )

    manager = MagicMock()
    channel = HttpRestChannel(config, manager=manager)

    await channel.start()

    try:
        await asyncio.sleep(0.5)

        async with httpx.AsyncClient() as client:
            response = await client.get("http://127.0.0.1:18773/api/v1/version")
            assert response.status_code == 200
            data = response.json()
            assert "version" in data
            assert data["protocol"] == "soothe-rest-v1"
    finally:
        await channel.stop()


@pytest.mark.asyncio
async def test_http_rest_docs_endpoint() -> None:
    """Test HTTP REST OpenAPI docs endpoint."""
    config = HttpRestConfig(
        enabled=True,
        host="127.0.0.1",
        port=18775,
        tls_enabled=False,
    )

    manager = MagicMock()
    channel = HttpRestChannel(config, manager=manager)

    await channel.start()

    try:
        await asyncio.sleep(0.5)

        async with httpx.AsyncClient() as client:
            # Test Swagger UI
            response = await client.get("http://127.0.0.1:18775/docs")
            assert response.status_code == 200

            # Test ReDoc
            response = await client.get("http://127.0.0.1:18775/redoc")
            assert response.status_code == 200
    finally:
        await channel.stop()
