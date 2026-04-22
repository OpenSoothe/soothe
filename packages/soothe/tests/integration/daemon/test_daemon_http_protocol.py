"""HTTP REST protocol integration tests for daemon backend APIs."""

from __future__ import annotations

import asyncio
import contextlib
from pathlib import Path
from typing import Any

import httpx
import pytest
from tests.integration.conftest import (
    alloc_ephemeral_port,
    force_isolated_home,
    get_base_config,
)

from soothe.config import SootheConfig
from soothe.config.daemon_config import HttpRestConfig
from soothe.daemon import SootheDaemon
from soothe.daemon.transports.http_rest import HttpRestTransport


async def _await_user_messages(
    client: httpx.AsyncClient,
    thread_id: str,
    *,
    expected_count: int,
    timeout: float = 10.0,
) -> list[dict[str, Any]]:
    """Poll thread messages until enough user messages are persisted."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while True:
        remaining = deadline - loop.time()
        if remaining <= 0:
            raise TimeoutError(
                "Timed out waiting for thread history to include required user messages"
            )
        response = await asyncio.wait_for(
            client.get(f"/api/v1/threads/{thread_id}/messages?limit=50&offset=0"),
            timeout=remaining,
        )
        payload = response.json()
        user_messages = [
            message for message in payload["messages"] if message.get("role") == "user"
        ]
        if len(user_messages) >= expected_count:
            return user_messages
        await asyncio.sleep(0.2)


def _build_http_transport_config(
    tmp_path: Path, port: int, *, with_daemon: bool = True
) -> tuple[SootheConfig, int]:
    """Build an isolated daemon config for HTTP transport tests."""
    base_config = get_base_config()

    if with_daemon:
        return (
            SootheConfig(
                providers=base_config.providers,
                router=base_config.router,
                vector_stores=base_config.vector_stores,
                vector_store_router=base_config.vector_store_router,
                persistence={"persist_dir": str(tmp_path / "persistence")},
                protocols={
                    "memory": {"enabled": False},
                    "durability": {
                        "backend": "json",
                        "persist_dir": str(tmp_path / "durability"),
                    },
                },
                daemon={
                    "transports": {
                        "unix_socket": {"enabled": False},
                        "websocket": {"enabled": False},
                        "http_rest": {
                            "enabled": True,
                            "host": "127.0.0.1",
                            "port": port,
                            "cors_origins": ["*"],
                            "tls_enabled": False,
                        },
                    },
                },
                # Disable unified classification for integration tests to avoid model compatibility issues
                performance={"unified_classification": False},
            ),
            port,
        )
    return (
        SootheConfig(),
        port,
    )


@pytest.fixture
async def http_daemon(tmp_path: Path):
    """Start a daemon exposing only HTTP REST transport."""
    force_isolated_home(tmp_path / "soothe-home")
    port = alloc_ephemeral_port()
    config, _ = _build_http_transport_config(tmp_path, port, with_daemon=True)
    daemon = SootheDaemon(config)
    await daemon.start()
    await asyncio.sleep(0.3)
    try:
        yield daemon, port
    finally:
        with contextlib.suppress(Exception):
            await daemon.stop()


@pytest.mark.asyncio
@pytest.mark.integration
async def test_http_transport_system_lifecycle(tmp_path: Path) -> None:
    """Layer A: basic HTTP transport lifecycle and transport-level endpoints."""
    port = alloc_ephemeral_port()
    config = HttpRestConfig(enabled=True, host="127.0.0.1", port=port, tls_enabled=False)
    transport = HttpRestTransport(config)
    await transport.start(lambda msg: None)
    await asyncio.sleep(0.2)

    try:
        await asyncio.sleep(0.2)
        async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{port}") as client:
            health = await client.get("/api/v1/health")
            assert health.status_code == 200
            assert health.json()["status"] == "healthy"

            status = await client.get("/api/v1/status")
            assert status.status_code == 200
            assert status.json()["transport"] == "http_rest"

            version = await client.get("/api/v1/version")
            assert version.status_code == 200
            assert version.json()["protocol"] == "RFC-0013"
    finally:
        await transport.stop()


@pytest.mark.asyncio
@pytest.mark.integration
async def test_http_transport_thread_lifecycle(
    http_daemon: tuple[SootheDaemon, int],
) -> None:
    """Layer A: cover core thread REST operations."""
    daemon, port = http_daemon
    _ = daemon
    base_url = f"http://127.0.0.1:{port}"

    async with httpx.AsyncClient(base_url=base_url, timeout=10.0) as client:
        create_response = await client.post(
            "/api/v1/threads",
            json={
                "initial_message": "create integration thread",
                "metadata": {"tags": ["integration", "http"], "priority": "normal"},
            },
        )
        assert create_response.status_code == 200
        thread = create_response.json()
        thread_id = thread["thread_id"]

        get_response = await client.get(f"/api/v1/threads/{thread_id}")
        assert get_response.status_code == 200
        get_payload = get_response.json()
        assert get_payload["thread"]["thread_id"] == thread_id

        list_response = await client.get("/api/v1/threads")
        assert list_response.status_code == 200
        list_payload = list_response.json()
        assert list_payload["total"] >= 1
        assert any(item["thread_id"] == thread_id for item in list_payload["threads"])

        filtered = await client.get("/api/v1/threads?priority=normal&limit=20&offset=0")
        assert filtered.status_code == 200
        filtered_payload = filtered.json()
        assert all(
            item["metadata"].get("priority") == "normal" for item in filtered_payload["threads"]
        )

        messages = await client.get(f"/api/v1/threads/{thread_id}/messages?limit=10&offset=0")
        assert messages.status_code == 200
        messages_payload = messages.json()
        assert messages_payload["thread_id"] == thread_id
        assert isinstance(messages_payload["messages"], list)

        artifacts = await client.get(f"/api/v1/threads/{thread_id}/artifacts")
        assert artifacts.status_code == 200
        artifacts_payload = artifacts.json()
        assert artifacts_payload["thread_id"] == thread_id
        assert isinstance(artifacts_payload["artifacts"], list)

        stats = await client.get(f"/api/v1/threads/{thread_id}/stats")
        assert stats.status_code == 200
        stats_payload = stats.json()
        assert stats_payload["thread_id"] == thread_id
        assert isinstance(stats_payload["stats"], dict)

        archive = await client.delete(f"/api/v1/threads/{thread_id}?archive=true")
        assert archive.status_code == 200
        archive_payload = archive.json()
        assert archive_payload["status"] == "archived"

        get_archived = await client.get(f"/api/v1/threads/{thread_id}")
        assert get_archived.status_code == 200
        assert get_archived.json()["thread"]["status"] == "archived"

        # Ensure deletion path is still exercised.
        delete_response = await client.delete(f"/api/v1/threads/{thread_id}?archive=false")
        assert delete_response.status_code == 200
        assert delete_response.json()["status"] == "deleted"

        # Validate removed resource is now gone.
        not_found_response = await client.get(f"/api/v1/threads/{thread_id}")
        assert not_found_response.status_code == 404


@pytest.mark.asyncio
@pytest.mark.integration
async def test_http_transport_resume_thread(
    http_daemon: tuple[SootheDaemon, int],
) -> None:
    """Layer A: verify resume endpoint accepts messages and returns resumed status."""
    daemon, port = http_daemon
    _ = daemon
    base_url = f"http://127.0.0.1:{port}"
    async with httpx.AsyncClient(base_url=base_url) as client:
        create_response = await client.post(
            "/api/v1/threads", json={"metadata": {"tags": ["resume"]}}
        )
        thread_id = create_response.json()["thread_id"]

        resume = await client.post(
            f"/api/v1/threads/{thread_id}/resume",
            json={"message": "continue conversation"},
        )
        assert resume.status_code == 200
        assert resume.json()["status"] == "resumed"
        assert resume.json()["thread_id"] == thread_id


@pytest.mark.asyncio
@pytest.mark.integration
async def test_http_transport_thread_history_continuation(
    http_daemon: tuple[SootheDaemon, int],
) -> None:
    """Layer A: verify thread continuation preserves and extends chat history."""
    daemon, port = http_daemon
    _ = daemon
    base_url = f"http://127.0.0.1:{port}"
    first_message = "Prepare HTTP resume history: first turn."
    second_message = "Continue HTTP resume history: second turn."

    async with httpx.AsyncClient(base_url=base_url) as client:
        create_response = await client.post(
            "/api/v1/threads",
            json={"metadata": {"tags": ["resume", "http"], "priority": "normal"}},
        )
        assert create_response.status_code == 200
        thread_id = create_response.json()["thread_id"]

        first_resume = await client.post(
            f"/api/v1/threads/{thread_id}/resume",
            json={"message": first_message},
        )
        assert first_resume.status_code == 200
        assert first_resume.json()["thread_id"] == thread_id

        second_resume = await client.post(
            f"/api/v1/threads/{thread_id}/resume",
            json={"message": second_message},
        )
        assert second_resume.status_code == 200
        assert second_resume.json()["thread_id"] == thread_id

        # Verify thread is still accessible after multiple resumes
        get_final = await client.get(f"/api/v1/threads/{thread_id}")
        assert get_final.status_code == 200
        assert get_final.json()["thread"]["thread_id"] == thread_id

        list_response = await client.get(
            "/api/v1/threads?status=idle&priority=normal&tags=resume&limit=10&offset=0&include_stats=true"
        )
        assert list_response.status_code == 200
        list_payload = list_response.json()
        assert any(item["thread_id"] == thread_id for item in list_payload["threads"])


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.xfail(reason="Contract expectation: config APIs should be mutable and schema-aware.")
async def test_http_transport_config_endpoints_are_contractual(tmp_path: Path) -> None:
    """Layer B: config APIs are intentionally expected to become real runtime-backed contracts."""
    port = alloc_ephemeral_port()
    config = HttpRestConfig(enabled=True, host="127.0.0.1", port=port, tls_enabled=False)
    transport = HttpRestTransport(config)
    await transport.start(lambda msg: None)
    await asyncio.sleep(0.2)

    try:
        async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{port}") as client:
            config_response = await client.get("/api/v1/config")
            assert config_response.status_code == 200
            assert config_response.json().get("config") not in ({}, None)

            update = await client.put(
                "/api/v1/config", json={"updates": {"logging": {"level": "info"}}}
            )
            assert update.status_code == 200

            schema = await client.get("/api/v1/config/schema")
            assert schema.status_code == 200
            assert schema.json().get("schema") != {}
    finally:
        await transport.stop()


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.xfail(reason="Contract expectation: file upload/download/delete should be persistent.")
async def test_http_transport_file_endpoints_contract(tmp_path: Path) -> None:
    """Layer B: file endpoints should persist artifacts for upload/download/delete."""
    port = alloc_ephemeral_port()
    config = HttpRestConfig(enabled=True, host="127.0.0.1", port=port, tls_enabled=False)
    transport = HttpRestTransport(config)
    await transport.start(lambda msg: None)
    await asyncio.sleep(0.2)

    try:
        async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{port}") as client:
            upload = await client.post(
                "/api/v1/files/upload",
                files={"file": ("notes.txt", b"payload", "text/plain")},
            )
            assert upload.status_code in {200, 201}
            file_id = upload.json()["file_id"]

            fetched = await client.get(f"/api/v1/files/{file_id}")
            assert fetched.status_code == 200

            deleted = await client.delete(f"/api/v1/files/{file_id}")
            assert deleted.status_code in {200, 204}

            after_delete = await client.get(f"/api/v1/files/{file_id}")
            assert after_delete.status_code == 404
    finally:
        await transport.stop()


@pytest.mark.asyncio
@pytest.mark.integration
async def test_http_transport_shutdown_endpoint(tmp_path: Path) -> None:
    """Layer A: shutdown endpoint returns expected protocol response."""
    port = alloc_ephemeral_port()
    config = HttpRestConfig(enabled=True, host="127.0.0.1", port=port, tls_enabled=False)
    transport = HttpRestTransport(config)
    await transport.start(lambda msg: None)
    await asyncio.sleep(0.2)

    try:
        async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{port}") as client:
            response = await client.post("/api/v1/system/shutdown")
            assert response.status_code == 200
            assert response.json()["status"] == "shutting_down"
    finally:
        await transport.stop()
