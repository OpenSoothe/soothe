"""Unit tests for ACPChannel."""

from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from soothe_daemon.channels.acp import ACPChannel, _make_text_block
from soothe_daemon.channels.base import Channel
from soothe_daemon.config.models import ACPConfig
from soothe_daemon.events.constants import OUTPUT_TEXT_DELTA


class TestACPChannelAttributes:
    """Tests for ACPChannel class-level attributes."""

    def test_channel_metadata(self):
        """Test channel name and display name."""
        assert ACPChannel.name == "acp"
        assert ACPChannel.display_name == "ACP"

    def test_capability_flags(self):
        """Test capability flags are correct."""
        assert ACPChannel.supports_inbound is True
        assert ACPChannel.supports_outbound is True
        assert ACPChannel.supports_streaming is True

    def test_inherits_from_channel(self):
        """Test inherits from Channel base class."""
        assert issubclass(ACPChannel, Channel)


class TestACPConfig:
    """Tests for ACPConfig model."""

    def test_default_config(self):
        """Test default config values."""
        cfg = ACPConfig()
        assert cfg.enabled is False
        assert cfg.agent_name == "Soothe"
        assert cfg.agent_description == "Soothe autonomous agent"
        assert cfg.default_model is None
        assert cfg.session_timeout_seconds == 3600

    def test_enabled_config(self):
        """Test enabled config."""
        cfg = ACPConfig(enabled=True, agent_name="Test", agent_description="desc")
        assert cfg.enabled is True
        assert cfg.agent_name == "Test"
        assert cfg.agent_description == "desc"

    def test_custom_model(self):
        """Test custom default_model."""
        cfg = ACPConfig(enabled=True, default_model="gpt-4o")
        assert cfg.default_model == "gpt-4o"


class MockManager:
    """Mock manager for testing."""

    _message_handler = None
    _handshake_callback = None
    _event_bus = None


class TestACPChannelInit:
    """Tests for ACPChannel initialization."""

    def test_basic_init(self):
        """Test basic initialization."""
        config = ACPConfig(enabled=True)
        manager = MockManager()

        channel = ACPChannel(config, manager)

        assert channel.name == "acp"
        assert channel.config == config
        assert channel._manager == manager
        assert channel.is_running is False
        assert channel._session_map == {}
        assert channel._pending_permissions == {}

    def test_client_count_zero(self):
        """Test client_count is zero initially."""
        config = ACPConfig(enabled=True)
        manager = MockManager()

        channel = ACPChannel(config, manager)

        assert channel.client_count == 0


class TestACPChannelSession:
    """Tests for ACPChannel session management."""

    @pytest.mark.asyncio
    async def test_session_new_creates_loop(self):
        """Test session/new creates a loop and populates _session_map."""
        config = ACPConfig(enabled=True)
        manager = MagicMock()
        manager.handle_inbound = AsyncMock(return_value="acp:test-session-id")
        manager._event_bus = MagicMock()
        manager._event_bus.subscribe = AsyncMock()

        channel = ACPChannel(config, manager)
        result = await channel._handle_session_new({})

        assert "sessionId" in result
        session_id = result["sessionId"]
        assert session_id in channel._session_map
        assert channel._session_map[session_id] == "acp:test-session-id"
        assert channel.client_count == 1

        # Clean up consumer task
        for task in channel._consumer_tasks.values():
            task.cancel()

    @pytest.mark.asyncio
    async def test_session_prompt_routes_to_manager(self):
        """Test session/prompt enqueues a user turn via handle_inbound."""
        config = ACPConfig(enabled=True)
        manager = MagicMock()
        manager.handle_inbound = AsyncMock(return_value="acp:test-session")
        manager._event_bus = MagicMock()
        manager._event_bus.subscribe = AsyncMock()

        channel = ACPChannel(config, manager)

        # Create session first
        new_result = await channel._handle_session_new({})
        session_id = new_result["sessionId"]

        manager.handle_inbound.reset_mock()
        await channel._handle_session_prompt(
            {"sessionId": session_id, "prompt": [{"type": "text", "text": "Hello"}]}
        )

        manager.handle_inbound.assert_called_once()
        call_kwargs = manager.handle_inbound.call_args
        assert call_kwargs.kwargs["content"] == "Hello"

        # Clean up consumer task
        for task in channel._consumer_tasks.values():
            task.cancel()

    @pytest.mark.asyncio
    async def test_session_cancel_publishes_event(self):
        """Test session/cancel publishes a cancel event on the loop topic."""
        config = ACPConfig(enabled=True)
        manager = MagicMock()
        manager.handle_inbound = AsyncMock(return_value="acp:cancel-test")
        manager._event_bus = MagicMock()
        manager._event_bus.subscribe = AsyncMock()
        manager._event_bus.publish = AsyncMock()

        channel = ACPChannel(config, manager)

        new_result = await channel._handle_session_new({})
        session_id = new_result["sessionId"]

        await channel._handle_session_cancel({"sessionId": session_id})

        manager._event_bus.publish.assert_called_once()
        published_msg = manager._event_bus.publish.call_args.args[1]
        assert published_msg["type"] == "command"
        assert published_msg["command"] == "cancel"

        # Clean up consumer task
        for task in channel._consumer_tasks.values():
            task.cancel()


class TestACPChannelEventTranslation:
    """Tests for daemon wire event → ACP block translation."""

    def test_translate_text_delta(self):
        """Test OUTPUT_TEXT_DELTA event translation."""
        config = ACPConfig(enabled=True)
        channel = ACPChannel(config, MockManager())

        event = {
            "type": "event",
            "loop_id": "test-loop",
            "data": {
                "type": OUTPUT_TEXT_DELTA,
                "content": "Hello world",
            },
        }

        blocks = channel._translate_event(event)
        assert len(blocks) == 1
        assert blocks[0]["type"] == "text"
        assert blocks[0]["text"] == "Hello world"

    def test_translate_unknown_event_returns_empty(self):
        """Test that unknown event types return empty list."""
        config = ACPConfig(enabled=True)
        channel = ACPChannel(config, MockManager())

        event = {"type": "event", "data": {"type": "unknown_type"}}
        blocks = channel._translate_event(event)
        assert blocks == []

    def test_make_text_block(self):
        """Test text block construction."""
        block = _make_text_block("test content")
        assert block["type"] == "text"
        assert block["text"] == "test content"


class TestACPChannelOutput:
    """Tests for ACPChannel stdout output."""

    @pytest.mark.asyncio
    async def test_write_jsonrpc_writes_to_stdout(self):
        """Test that _write_jsonrpc writes NDJSON to stdout."""
        config = ACPConfig(enabled=True)
        channel = ACPChannel(config, MockManager())

        msg = {"jsonrpc": "2.0", "method": "test", "params": {}}
        with patch("soothe_daemon.channels.acp._write_stdout") as mock_write:
            await channel._write_jsonrpc(msg)
            mock_write.assert_called_once()
            written = mock_write.call_args.args[0]
            assert json.loads(written) == msg
            assert written.endswith("\n")


class TestACPPermissionBridge:
    """Tests for the permission model bridge (session/request_permission)."""

    def _make_channel_with_session(self) -> tuple[ACPChannel, str, str]:
        """Create a channel with a registered session for testing.

        Returns:
            (channel, session_id, loop_id) tuple.
        """
        config = ACPConfig(enabled=True)
        manager = MagicMock()
        manager.handle_inbound = AsyncMock(return_value="acp:perm-test")
        manager._event_bus = MagicMock()
        manager._event_bus.subscribe = AsyncMock()
        manager._event_bus.publish = AsyncMock()

        channel = ACPChannel(config, manager)
        # Manually register a session without starting consumer task
        session_id = "test-session-123"
        loop_id = "acp:perm-test"
        channel._session_map[session_id] = loop_id
        return channel, session_id, loop_id

    def test_is_tool_approval_event_positive(self):
        """Test that __interrupt__ with action_requests is detected."""
        channel, _, _ = self._make_channel_with_session()

        event = {
            "type": "event",
            "loop_id": "acp:perm-test",
            "data": {
                "__interrupt__": {
                    "interrupt_id": "int-001",
                    "action_requests": [
                        {
                            "tool_call_id": "tc-1",
                            "tool_name": "write_file",
                            "args": {"path": "/etc/passwd"},
                        }
                    ],
                }
            },
        }
        assert channel._is_tool_approval_event(event) is True

    def test_is_tool_approval_event_negative(self):
        """Test that non-interrupt events are not detected as tool-approval."""
        channel, _, _ = self._make_channel_with_session()

        event = {
            "type": "event",
            "data": {"type": "soothe.output.text.delta", "content": "hello"},
        }
        assert channel._is_tool_approval_event(event) is False

    def test_is_tool_approval_event_no_action_requests(self):
        """Test __interrupt__ without action_requests is not tool-approval."""
        channel, _, _ = self._make_channel_with_session()

        event = {
            "data": {"__interrupt__": {"type": "ask_user", "questions": []}},
        }
        assert channel._is_tool_approval_event(event) is False

    @pytest.mark.asyncio
    async def test_permission_request_sends_to_client(self):
        """Test that a permission request is sent to the ACP client via stdout."""
        channel, session_id, loop_id = self._make_channel_with_session()

        event = {
            "type": "event",
            "loop_id": loop_id,
            "data": {
                "__interrupt__": {
                    "interrupt_id": "int-001",
                    "action_requests": [
                        {
                            "tool_call_id": "tc-1",
                            "tool_name": "write_file",
                            "args": {"path": "/etc/passwd"},
                        }
                    ],
                }
            },
        }

        # Patch _write_jsonrpc to capture the outbound request
        written_messages: list[dict] = []

        async def _capture_write(msg):
            written_messages.append(msg)

        with patch.object(channel, "_write_jsonrpc", _capture_write):
            # Start the bridge in a task so we can control the future
            bridge_task = asyncio.create_task(
                channel._bridge_permission_request(session_id, loop_id, event)
            )
            await asyncio.sleep(0.1)

            # Verify the permission request was written
            assert len(written_messages) == 1
            req = written_messages[0]
            assert req["method"] == "session/request_permission"
            assert req["params"]["sessionId"] == session_id
            assert req["params"]["toolCall"]["toolCallId"] == "tc-1"
            assert len(req["params"]["options"]) == 4

            # Resolve the pending future with "allow"
            req_id = req["id"]
            fut = channel._pending_permissions[req_id]
            fut.set_result({"outcome": "selected", "optionId": "allow_once"})

            # Wait for the bridge to complete
            await asyncio.wait_for(bridge_task, timeout=5.0)

        # Verify resume was published on the EventBus
        channel._manager._event_bus.publish.assert_called()
        resume_msg = channel._manager._event_bus.publish.call_args.args[1]
        assert resume_msg["type"] == "command"
        assert resume_msg["command"] == "resume"
        assert "int-001" in resume_msg["resume_payload"]
        assert resume_msg["resume_payload"]["int-001"]["decisions"][0]["type"] == "approve"

        # Clean up
        for task in channel._consumer_tasks.values():
            task.cancel()

    @pytest.mark.asyncio
    async def test_permission_deny_routes_reject(self):
        """Test that a deny response routes a reject decision."""
        channel, session_id, loop_id = self._make_channel_with_session()

        event = {
            "type": "event",
            "loop_id": loop_id,
            "data": {
                "__interrupt__": {
                    "interrupt_id": "int-002",
                    "action_requests": [
                        {
                            "tool_call_id": "tc-2",
                            "tool_name": "run_command",
                            "args": {"command": "rm -rf /"},
                        }
                    ],
                }
            },
        }

        written_messages: list[dict] = []

        async def _capture_write(msg):
            written_messages.append(msg)

        with patch.object(channel, "_write_jsonrpc", _capture_write):
            bridge_task = asyncio.create_task(
                channel._bridge_permission_request(session_id, loop_id, event)
            )
            await asyncio.sleep(0.1)

            req_id = written_messages[0]["id"]
            fut = channel._pending_permissions[req_id]
            fut.set_result({"outcome": "selected", "optionId": "reject_once"})

            await asyncio.wait_for(bridge_task, timeout=5.0)

        resume_msg = channel._manager._event_bus.publish.call_args.args[1]
        assert resume_msg["resume_payload"]["int-002"]["decisions"][0]["type"] == "reject"

        for task in channel._consumer_tasks.values():
            task.cancel()

    @pytest.mark.asyncio
    async def test_permission_timeout_routes_reject(self):
        """Test that a timeout routes a reject decision."""
        channel, session_id, loop_id = self._make_channel_with_session()

        event = {
            "type": "event",
            "loop_id": loop_id,
            "data": {
                "__interrupt__": {
                    "interrupt_id": "int-003",
                    "action_requests": [
                        {"tool_call_id": "tc-3", "tool_name": "delete", "args": {}}
                    ],
                }
            },
        }

        written_messages: list[dict] = []

        async def _capture_write(msg):
            written_messages.append(msg)

        # Use a very short timeout to make the test fast
        with (
            patch.object(channel, "_write_jsonrpc", _capture_write),
            patch("soothe_daemon.channels.acp._PERMISSION_TIMEOUT_S", 0.2),
        ):
            bridge_task = asyncio.create_task(
                channel._bridge_permission_request(session_id, loop_id, event)
            )
            await asyncio.wait_for(bridge_task, timeout=5.0)

        # Verify reject was routed
        resume_msg = channel._manager._event_bus.publish.call_args.args[1]
        assert resume_msg["resume_payload"]["int-003"]["decisions"][0]["type"] == "reject"

        for task in channel._consumer_tasks.values():
            task.cancel()

    @pytest.mark.asyncio
    async def test_handle_response_resolves_pending_future(self):
        """Test that _handle_response resolves a pending permission future."""
        channel, session_id, loop_id = self._make_channel_with_session()

        # Create a pending permission
        req_id = 42
        fut: asyncio.Future[dict] = asyncio.get_running_loop().create_future()
        channel._pending_permissions[req_id] = fut

        # Simulate a response from the ACP client
        response = {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {"outcome": "selected", "optionId": "allow_always"},
        }
        await channel._handle_response(response)

        assert fut.done()
        result = fut.result()
        assert result["outcome"] == "selected"
        assert result["optionId"] == "allow_always"
        assert req_id not in channel._pending_permissions

    @pytest.mark.asyncio
    async def test_handle_response_with_error_resolves_cancelled(self):
        """Test that an error response resolves as cancelled."""
        channel, _, _ = self._make_channel_with_session()

        req_id = 99
        fut: asyncio.Future[dict] = asyncio.get_running_loop().create_future()
        channel._pending_permissions[req_id] = fut

        response = {
            "jsonrpc": "2.0",
            "id": req_id,
            "error": {"code": -1, "message": "denied"},
        }
        await channel._handle_response(response)

        assert fut.done()
        assert fut.result()["outcome"] == "cancelled"

    @pytest.mark.asyncio
    async def test_handle_response_unknown_id(self):
        """Test that a response with unknown request id is ignored."""
        channel, _, _ = self._make_channel_with_session()

        response = {"jsonrpc": "2.0", "id": 999, "result": {}}
        # Should not raise
        await channel._handle_response(response)
        assert len(channel._pending_permissions) == 0

    @pytest.mark.asyncio
    async def test_dispatch_request_routes_response(self):
        """Test that _dispatch_request routes a response (no method) to _handle_response."""
        channel, _, _ = self._make_channel_with_session()

        req_id = 55
        fut: asyncio.Future[dict] = asyncio.get_running_loop().create_future()
        channel._pending_permissions[req_id] = fut

        # A response has no "method" key but has "id"
        response = {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {"outcome": "selected", "optionId": "allow_once"},
        }
        await channel._dispatch_request(response)

        assert fut.done()
        assert fut.result()["optionId"] == "allow_once"

    @pytest.mark.asyncio
    async def test_stop_cancels_pending_permissions(self):
        """Test that stop() cancels pending permission futures."""
        config = ACPConfig(enabled=True)
        manager = MagicMock()
        manager._event_bus = MagicMock()

        channel = ACPChannel(config, manager)
        channel._running = True

        req_id = 77
        fut: asyncio.Future[dict] = asyncio.get_running_loop().create_future()
        channel._pending_permissions[req_id] = fut

        await channel.stop()

        assert fut.cancelled() or fut.done()
        assert len(channel._pending_permissions) == 0
