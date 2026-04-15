"""Integration tests for CLI-daemon WebSocket communication.

Tests the split architecture:
- CLI package communicates with daemon via WebSocket only
- No direct imports from daemon runtime in CLI
- Protocol compliance between SDK client and daemon server
"""

import asyncio
import pytest
from soothe_sdk.client import WebSocketClient, connect_websocket_with_retries
from soothe_sdk.protocol import encode, decode


@pytest.mark.asyncio
async def test_sdk_websocket_client_imports():
    """Verify SDK WebSocket client can be imported independently."""
    # This should work without any daemon imports
    client = WebSocketClient(url="ws://localhost:8765")
    assert client is not None
    assert hasattr(client, 'connect')
    assert hasattr(client, 'send')
    assert hasattr(client, 'read_event')


@pytest.mark.asyncio
async def test_sdk_protocol_encode_decode():
    """Test protocol encode/decode roundtrip."""
    message = {
        "type": "test",
        "data": "sample",
        "nested": {"key": "value"}
    }

    # Encode
    encoded = encode(message)
    assert isinstance(encoded, bytes)
    assert encoded.endswith(b"\n")

    # Decode
    decoded = decode(encoded)
    assert decoded == message


@pytest.mark.asyncio
async def test_cli_package_imports():
    """Verify CLI package imports work without daemon dependencies."""
    # CLI should import only from SDK, not daemon
    from soothe_cli.cli.main import app

    assert app is not None
    assert app.info.name == "soothe"


@pytest.mark.asyncio
async def test_daemon_package_imports():
    """Verify daemon package imports work."""
    # Daemon should import from both SDK and its own modules
    from soothe_daemon.cli.main import app as daemon_app

    assert daemon_app is not None
    assert daemon_app.info.name == "soothe-daemon"


@pytest.mark.asyncio
async def test_no_cli_daemon_imports():
    """Verify CLI does NOT import daemon runtime modules.

    This is the critical architectural constraint.
    """
    import sys
    import importlib.util

    # Try to import CLI
    spec = importlib.util.find_spec("soothe_cli")
    cli_module = importlib.util.module_from_spec(spec)
    sys.modules["soothe_cli"] = cli_module
    spec.loader.exec_module(cli_module)

    # Check that daemon runtime modules are NOT loaded
    forbidden_modules = [
        "soothe_daemon.core.runner",
        "soothe_daemon.tools",
        "soothe_daemon.subagents",
    ]

    for module_name in forbidden_modules:
        assert module_name not in sys.modules, f"CLI should NOT import {module_name}"


@pytest.mark.asyncio
async def test_sdk_shared_between_packages():
    """Verify SDK is shared between CLI and daemon."""
    from soothe_sdk.client import WebSocketClient
    from soothe_cli.cli.main import app  # CLI imports SDK
    from soothe_daemon.cli.main import app as daemon_app  # Daemon imports SDK

    # Both should be able to use WebSocketClient
    client_for_cli = WebSocketClient()
    client_for_daemon = WebSocketClient()

    # Same class from same package
    assert type(client_for_cli) == type(client_for_daemon)
    assert client_for_cli.__class__.__module__ == "soothe_sdk.client.websocket"


@pytest.mark.asyncio
async def test_protocol_message_types():
    """Test that protocol message types are properly defined."""
    # Test input message
    input_msg = {
        "type": "input",
        "text": "test query",
        "autonomous": False
    }

    encoded = encode(input_msg)
    decoded = decode(encoded)
    assert decoded["type"] == "input"

    # Test thread_list message
    thread_list_msg = {
        "type": "thread_list",
        "filter": {"status": "active"}
    }

    encoded = encode(thread_list_msg)
    decoded = decode(encoded)
    assert decoded["type"] == "thread_list"


@pytest.mark.asyncio
async def test_package_entry_points():
    """Test that both entry points are properly defined."""
    import subprocess

    # Test soothe command
    result = subprocess.run(
        ["soothe", "--help"],
        capture_output=True,
        text=True
    )
    assert result.returncode == 0
    assert "Intelligent AI assistant" in result.stdout

    # Test soothe-daemon command
    result = subprocess.run(
        ["soothe-daemon", "--help"],
        capture_output=True,
        text=True
    )
    assert result.returncode == 0
    assert "daemon server" in result.stdout


if __name__ == "__main__":
    pytest.main([__file__, "-v"])