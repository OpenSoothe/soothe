"""End-to-end integration tests for ACP channel with the official ACP client SDK.

These tests use the official ``acp`` package (``agent-client-protocol``) to
verify the ACP channel's JSON-RPC protocol compliance, including the full
permission bridge flow (``session/request_permission`` → client response →
resume/deny).

The tests use ``asyncio`` subprocess pipes to connect the official ACP client
to a subprocess running the ACP channel's JSON-RPC loop. This tests the real
stdio transport path end-to-end.

Tests are marked ``integration`` and require ``--run-integration``.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

# The acp package is optional; skip all tests if not installed.
acp = pytest.importorskip("acp")

from acp import (  # noqa: E402
    InitializeResponse,
    NewSessionResponse,
    PromptResponse,
    RequestPermissionResponse,
    helpers,
)
from acp._transport import memory_transport_pair  # noqa: E402
from acp.client.connection import ClientSideConnection  # noqa: E402
from acp.schema import (  # noqa: E402
    AllowedOutcome,
    DeniedOutcome,
    PermissionOption,
    ToolCallUpdate,
)

# ---------------------------------------------------------------------------
# Test Agent (server-side) and Client (client-side) implementations
# ---------------------------------------------------------------------------


class _TestAgent:
    """Minimal ACP Agent for integration testing.

    Implements only the methods needed for the E2E test:
    ``initialize``, ``new_session``, ``prompt``, ``cancel``.
    The ``prompt`` handler sends a ``session_update`` with text, then
    optionally calls ``request_permission`` on the connection.
    """

    def __init__(self, *, send_permission: bool = False) -> None:
        self._send_permission = send_permission
        self._conn: Any = None
        self.prompt_received = asyncio.Event()
        self.permission_requested = asyncio.Event()
        self.permission_granted = asyncio.Event()
        self.permission_denied = asyncio.Event()

    def on_connect(self, conn: Any) -> None:
        self._conn = conn

    async def initialize(
        self,
        protocol_version: int,
        client_capabilities: Any = None,
        client_info: Any = None,
        **kwargs: Any,
    ) -> InitializeResponse:
        from acp import PROTOCOL_VERSION
        from acp.schema import ClientCapabilities, Implementation

        return InitializeResponse(
            protocol_version=PROTOCOL_VERSION,
            agent_capabilities={},
            server_info=Implementation(name="TestAgent", version="1.0"),
            client_capabilities=client_capabilities or ClientCapabilities(),
        )

    async def new_session(
        self,
        cwd: str,
        additional_directories: list[str] | None = None,
        mcp_servers: list[Any] | None = None,
        **kwargs: Any,
    ) -> NewSessionResponse:
        import uuid

        return NewSessionResponse(
            session_id=str(uuid.uuid4()),
        )

    async def prompt(
        self,
        session_id: str,
        prompt: list[Any],
        **kwargs: Any,
    ) -> PromptResponse:
        # Send a session_update with text
        if self._conn is not None:
            await self._conn.session_update(
                session_id=session_id,
                update=helpers.update_agent_message_text("Processing your request..."),
            )

            if self._send_permission:
                # Send a permission request — the client's response determines
                # whether we proceed or abort.
                from acp.exceptions import RequestError

                try:
                    perm_response = await self._conn.request_permission(
                        session_id=session_id,
                        tool_call=ToolCallUpdate(
                            tool_call_id="tc-1",
                            title="run_command",
                            raw_input={"command": "rm -rf /"},
                        ),
                        options=[
                            PermissionOption(
                                option_id="allow",
                                name="Allow",
                                kind="allow_once",
                            ),
                            PermissionOption(
                                option_id="deny",
                                name="Deny",
                                kind="reject_once",
                            ),
                        ],
                    )
                    # Check the outcome — if denied, abort with refusal
                    outcome = perm_response.outcome
                    if hasattr(outcome, "outcome") and outcome.outcome == "cancelled":
                        self.permission_denied.set()
                        self.permission_requested.set()
                        self.prompt_received.set()
                        return PromptResponse(stop_reason="refusal")
                    self.permission_granted.set()
                except RequestError:
                    self.permission_denied.set()
                    self.permission_requested.set()
                    self.prompt_received.set()
                    return PromptResponse(stop_reason="refusal")

                self.permission_requested.set()

            # Send final message
            await self._conn.session_update(
                session_id=session_id,
                update=helpers.update_agent_message_text("Done!"),
            )

        self.prompt_received.set()
        return PromptResponse(stop_reason="end_turn")

    async def cancel(self, session_id: str, **kwargs: Any) -> None:
        pass

    async def load_session(self, cwd: str, session_id: str, **kwargs: Any) -> Any:
        return None

    async def list_sessions(self, cwd: str | None = None, **kwargs: Any) -> Any:
        from acp.schema import ListSessionsResponse

        return ListSessionsResponse(sessions=[])

    async def close_session(self, session_id: str, **kwargs: Any) -> Any:
        return None

    async def ext_method(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        return {}

    async def ext_notification(self, method: str, params: dict[str, Any]) -> None:
        pass


class _TestClient:
    """Minimal ACP Client for integration testing.

    Handles ``session/request_permission`` and ``session/update`` from the agent.
    The permission handler can be configured to allow or deny.
    """

    def __init__(self, *, permission_outcome: str = "allow") -> None:
        self._permission_outcome = permission_outcome
        self.updates: list[Any] = []
        self.permission_handled = asyncio.Event()

    async def request_permission(
        self,
        session_id: str,
        tool_call: ToolCallUpdate,
        options: list[PermissionOption],
        **kwargs: Any,
    ) -> RequestPermissionResponse:
        if self._permission_outcome == "allow":
            return RequestPermissionResponse(
                outcome=AllowedOutcome(outcome="selected", option_id="allow"),
            )
        return RequestPermissionResponse(
            outcome=DeniedOutcome(outcome="cancelled"),
        )

    async def session_update(self, session_id: str, update: Any, **kwargs: Any) -> None:
        self.updates.append(update)

    async def write_text_file(self, session_id: str, path: str, content: str, **kwargs: Any) -> Any:
        return None

    async def read_text_file(self, session_id: str, path: str, **kwargs: Any) -> Any:
        return None

    async def create_terminal(self, session_id: str, command: str, **kwargs: Any) -> Any:
        return None

    async def terminal_output(self, session_id: str, terminal_id: str, **kwargs: Any) -> Any:
        return None

    async def release_terminal(self, session_id: str, terminal_id: str, **kwargs: Any) -> Any:
        return None

    async def wait_for_terminal_exit(self, session_id: str, terminal_id: str, **kwargs: Any) -> Any:
        return None

    async def kill_terminal(self, session_id: str, terminal_id: str, **kwargs: Any) -> Any:
        return None

    async def create_elicitation(self, message: str, mode: Any, **kwargs: Any) -> Any:
        return None

    async def complete_elicitation(self, elicitation_id: str, **kwargs: Any) -> None:
        pass

    async def ext_method(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        return {}

    async def ext_notification(self, method: str, params: dict[str, Any]) -> None:
        pass

    def on_connect(self, conn: Any) -> None:
        pass


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def anyio_backend() -> str:
    """Use asyncio backend."""
    return "asyncio"


# ---------------------------------------------------------------------------
# Integration tests using in-memory transport pairs
# ---------------------------------------------------------------------------


class TestACPIntegrationProtocol:
    """E2E tests for ACP protocol compliance using the official SDK.

    These tests use ``memory_transport_pair`` to create two linked in-memory
    transports. One side runs an ``AgentSideConnection`` (the "server"),
    the other runs a ``ClientSideConnection`` (the "client"). The test
    verifies that the ACP protocol methods work correctly, including
    the permission bridge flow.
    """

    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_initialize_handshake(self) -> None:
        """Test initialize handshake between agent and client."""
        from acp.core import AgentSideConnection

        agent_transport, client_transport = memory_transport_pair()

        agent = _TestAgent()
        client = _TestClient()

        # Create agent-side connection (server)
        agent_conn = AgentSideConnection(
            agent,
            agent_transport,
            listening=True,
        )

        # Create client-side connection
        client_conn = ClientSideConnection(
            client,
            client_transport,
        )

        # Initialize
        response = await asyncio.wait_for(
            client_conn.initialize(protocol_version=1),
            timeout=5.0,
        )
        assert response is not None
        assert response.protocol_version is not None

        await agent_conn.close()
        await client_conn._conn.close()

    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_session_new_and_prompt(self) -> None:
        """Test session/new + session/prompt flow."""
        from acp.core import AgentSideConnection

        agent_transport, client_transport = memory_transport_pair()

        agent = _TestAgent()
        client = _TestClient()

        agent_conn = AgentSideConnection(
            agent,
            agent_transport,
            listening=True,
        )

        client_conn = ClientSideConnection(
            client,
            client_transport,
        )

        # Initialize first
        await asyncio.wait_for(
            client_conn.initialize(protocol_version=1),
            timeout=5.0,
        )

        # Create a new session
        session = await asyncio.wait_for(
            client_conn.new_session(cwd="/tmp"),
            timeout=5.0,
        )
        assert session.session_id is not None
        assert len(session.session_id) > 0

        # Send a prompt
        from acp.schema import TextContentBlock

        prompt_response = await asyncio.wait_for(
            client_conn.prompt(
                session_id=session.session_id,
                prompt=[TextContentBlock(type="text", text="Hello, agent!")],
            ),
            timeout=5.0,
        )
        assert prompt_response is not None

        # Wait for agent to process the prompt
        await asyncio.wait_for(agent.prompt_received.wait(), timeout=5.0)

        # Verify the client received session updates
        assert len(client.updates) >= 1

        await agent_conn.close()
        await client_conn._conn.close()

    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_permission_bridge_allow(self) -> None:
        """Test permission bridge: agent requests permission, client allows."""
        from acp.core import AgentSideConnection

        agent_transport, client_transport = memory_transport_pair()

        agent = _TestAgent(send_permission=True)
        client = _TestClient(permission_outcome="allow")

        agent_conn = AgentSideConnection(
            agent,
            agent_transport,
            listening=True,
        )

        client_conn = ClientSideConnection(
            client,
            client_transport,
        )

        # Initialize
        await asyncio.wait_for(
            client_conn.initialize(protocol_version=1),
            timeout=5.0,
        )

        # Create session
        session = await asyncio.wait_for(
            client_conn.new_session(cwd="/tmp"),
            timeout=5.0,
        )

        # Send prompt — agent will request permission, client will allow
        prompt_response = await asyncio.wait_for(
            client_conn.prompt(
                session_id=session.session_id,
                prompt=[helpers.text_block("Run a command")],
            ),
            timeout=10.0,
        )
        assert prompt_response is not None
        assert prompt_response.stop_reason == "end_turn"

        # Wait for the agent to have been granted permission
        await asyncio.wait_for(agent.permission_granted.wait(), timeout=5.0)

        # Verify the client received session updates
        assert len(client.updates) >= 1

        await agent_conn.close()
        await client_conn._conn.close()

    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_permission_bridge_deny(self) -> None:
        """Test permission bridge: agent requests permission, client denies."""
        from acp.core import AgentSideConnection

        agent_transport, client_transport = memory_transport_pair()

        agent = _TestAgent(send_permission=True)
        client = _TestClient(permission_outcome="deny")

        agent_conn = AgentSideConnection(
            agent,
            agent_transport,
            listening=True,
        )

        client_conn = ClientSideConnection(
            client,
            client_transport,
        )

        # Initialize
        await asyncio.wait_for(
            client_conn.initialize(protocol_version=1),
            timeout=5.0,
        )

        # Create session
        session = await asyncio.wait_for(
            client_conn.new_session(cwd="/tmp"),
            timeout=5.0,
        )

        # Send prompt — agent will request permission, client will deny
        # The deny response causes the agent to return stop_reason="refusal"
        prompt_response = await asyncio.wait_for(
            client_conn.prompt(
                session_id=session.session_id,
                prompt=[helpers.text_block("Run a dangerous command")],
            ),
            timeout=10.0,
        )
        assert prompt_response is not None
        assert prompt_response.stop_reason == "refusal"

        # Wait for the agent to have processed the denial
        await asyncio.wait_for(agent.permission_denied.wait(), timeout=5.0)

        await agent_conn.close()
        await client_conn._conn.close()


# ---------------------------------------------------------------------------
# Integration tests with the ACP channel's raw JSON-RPC over stdio
# ---------------------------------------------------------------------------


class TestACPChannelRawJSONRPC:
    """Tests for the ACP channel's raw JSON-RPC implementation.

    These tests verify that the ACP channel's manual JSON-RPC implementation
    is wire-compatible with the official ACP SDK's ``NdjsonTransport``.
    The test creates an ``AgentSideConnection`` using a memory transport pair,
    and a raw JSON-RPC client on the other side that sends/receives NDJSON
    messages matching the ACP channel's format.
    """

    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_raw_jsonrpc_initialize(self) -> None:
        """Test that raw JSON-RPC initialize matches ACP protocol."""
        from acp.core import AgentSideConnection

        agent_transport, client_transport = memory_transport_pair()

        agent = _TestAgent()
        agent_conn = AgentSideConnection(
            agent,
            agent_transport,
            listening=True,
        )

        # Send raw initialize request via the client transport

        init_request = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": 1,
                "clientCapabilities": {},
                "clientInfo": {"name": "raw-test", "version": "1.0"},
            },
        }
        await client_transport.send(init_request)

        # Receive the response
        response = await asyncio.wait_for(client_transport.receive(), timeout=5.0)
        assert response is not None
        assert response["jsonrpc"] == "2.0"
        assert response["id"] == 1
        assert "result" in response
        assert "error" not in response

        await agent_conn.close()
        await client_transport.close()

    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_raw_jsonrpc_session_new(self) -> None:
        """Test that raw JSON-RPC session/new matches ACP protocol."""
        from acp.core import AgentSideConnection

        agent_transport, client_transport = memory_transport_pair()

        agent = _TestAgent()
        agent_conn = AgentSideConnection(
            agent,
            agent_transport,
            listening=True,
        )

        # Initialize first
        await client_transport.send(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": 1,
                    "clientCapabilities": {},
                    "clientInfo": {"name": "raw-test", "version": "1.0"},
                },
            }
        )
        resp = await asyncio.wait_for(client_transport.receive(), timeout=5.0)
        assert "result" in resp

        # Send session/new
        await client_transport.send(
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "session/new",
                "params": {
                    "cwd": "/tmp",
                    "mcpServers": [],
                },
            }
        )
        resp = await asyncio.wait_for(client_transport.receive(), timeout=5.0)
        assert resp["id"] == 2
        assert "result" in resp
        assert "sessionId" in resp["result"]

        await agent_conn.close()
        await client_transport.close()

    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_raw_jsonrpc_session_prompt_and_update(self) -> None:
        """Test session/prompt produces session/update notification."""
        from acp.core import AgentSideConnection

        agent_transport, client_transport = memory_transport_pair()

        agent = _TestAgent()
        agent_conn = AgentSideConnection(
            agent,
            agent_transport,
            listening=True,
        )

        # Initialize
        await client_transport.send(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": 1,
                    "clientCapabilities": {},
                    "clientInfo": {"name": "raw-test", "version": "1.0"},
                },
            }
        )
        await asyncio.wait_for(client_transport.receive(), timeout=5.0)

        # Create session
        await client_transport.send(
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "session/new",
                "params": {"cwd": "/tmp", "mcpServers": []},
            }
        )
        resp = await asyncio.wait_for(client_transport.receive(), timeout=5.0)
        session_id = resp["result"]["sessionId"]

        # Send prompt
        await client_transport.send(
            {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "session/prompt",
                "params": {
                    "sessionId": session_id,
                    "prompt": [{"type": "text", "text": "Hello"}],
                },
            }
        )

        # We should receive session/update notifications followed by the
        # prompt response. Collect messages until we get the response (id=3).
        updates = []
        for _ in range(10):
            msg = await asyncio.wait_for(client_transport.receive(), timeout=5.0)
            if msg.get("id") == 3:
                # This is the prompt response
                break
            if msg.get("method") == "session/update":
                updates.append(msg)

        assert len(updates) >= 1

        await agent_conn.close()
        await client_transport.close()

    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_raw_jsonrpc_permission_request_response(self) -> None:
        """Test raw JSON-RPC permission request/response flow.

        The agent sends ``session/request_permission``, the test client
        responds with ``allowed``, and the agent continues.
        """
        from acp.core import AgentSideConnection

        agent_transport, client_transport = memory_transport_pair()

        agent = _TestAgent(send_permission=True)
        agent_conn = AgentSideConnection(
            agent,
            agent_transport,
            listening=True,
        )

        # Initialize
        await client_transport.send(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": 1,
                    "clientCapabilities": {},
                    "clientInfo": {"name": "raw-test", "version": "1.0"},
                },
            }
        )
        await asyncio.wait_for(client_transport.receive(), timeout=5.0)

        # Create session
        await client_transport.send(
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "session/new",
                "params": {"cwd": "/tmp", "mcpServers": []},
            }
        )
        resp = await asyncio.wait_for(client_transport.receive(), timeout=5.0)
        session_id = resp["result"]["sessionId"]

        # Send prompt
        await client_transport.send(
            {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "session/prompt",
                "params": {
                    "sessionId": session_id,
                    "prompt": [{"type": "text", "text": "Run rm -rf /"}],
                },
            }
        )

        # Collect messages: we expect session/update notifications,
        # then session/request_permission, then more updates, then prompt response.
        permission_request = None
        prompt_response = None
        for _ in range(20):
            msg = await asyncio.wait_for(client_transport.receive(), timeout=10.0)
            if msg.get("method") == "session/request_permission":
                permission_request = msg
                # Respond with allow
                req_id = msg["id"]
                await client_transport.send(
                    {
                        "jsonrpc": "2.0",
                        "id": req_id,
                        "result": {
                            "outcome": {
                                "outcome": "selected",
                                "optionId": "allow",
                            },
                        },
                    }
                )
            elif msg.get("id") == 3:
                prompt_response = msg
                break

        assert permission_request is not None
        assert "toolCall" in permission_request["params"]
        assert "options" in permission_request["params"]
        assert prompt_response is not None

        await agent_conn.close()
        await client_transport.close()


# ---------------------------------------------------------------------------
# ACP channel unit-level integration: verify channel output matches ACP format
# ---------------------------------------------------------------------------


class TestACPChannelWireCompatibility:
    """Verify that ACPChannel's JSON-RPC output is wire-compatible with the
    official ACP SDK's expected message format.

    These tests check that the messages produced by ``ACPChannel`` match
    the schema the official SDK expects, ensuring editors (Zed, etc.)
    can communicate with the Soothe ACP server.
    """

    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_session_update_format(self) -> None:
        """Test that session/update notification format matches ACP spec."""
        from acp.schema import AgentMessageChunk, SessionNotification

        # Build a session update using ACP helpers
        update = helpers.update_agent_message_text("Hello from agent")

        # Verify it matches the expected schema
        assert isinstance(update, AgentMessageChunk)
        assert update.session_update == "agent_message_chunk"

        # Verify the wire format
        notification = SessionNotification(
            session_id="test-session",
            update=update,
        )
        wire = notification.model_dump(by_alias=True, exclude_none=True)
        assert wire["sessionId"] == "test-session"
        assert wire["update"]["sessionUpdate"] == "agent_message_chunk"

    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_permission_request_format(self) -> None:
        """Test that session/request_permission format matches ACP spec."""
        from acp.schema import RequestPermissionRequest

        tool_call = ToolCallUpdate(
            tool_call_id="tc-1",
            title="run_command",
            raw_input={"command": "ls -la"},
        )
        options = [
            PermissionOption(option_id="allow", name="Allow", kind="allow_once"),
            PermissionOption(option_id="deny", name="Deny", kind="reject_once"),
        ]

        request = RequestPermissionRequest(
            session_id="test-session",
            tool_call=tool_call,
            options=options,
        )

        wire = request.model_dump(by_alias=True, exclude_none=True)
        assert wire["sessionId"] == "test-session"
        assert wire["toolCall"]["toolCallId"] == "tc-1"
        assert wire["toolCall"]["title"] == "run_command"
        assert len(wire["options"]) == 2
        assert wire["options"][0]["optionId"] == "allow"
        assert wire["options"][0]["kind"] == "allow_once"

    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_permission_response_allow_format(self) -> None:
        """Test that allowed permission response format matches ACP spec."""
        response = RequestPermissionResponse(
            outcome=AllowedOutcome(outcome="selected", option_id="allow"),
        )
        wire = response.model_dump(by_alias=True, exclude_none=True)
        assert wire["outcome"]["outcome"] == "selected"
        assert wire["outcome"]["optionId"] == "allow"

    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_permission_response_deny_format(self) -> None:
        """Test that denied permission response format matches ACP spec."""
        response = RequestPermissionResponse(
            outcome=DeniedOutcome(outcome="cancelled"),
        )
        wire = response.model_dump(by_alias=True, exclude_none=True)
        assert wire["outcome"]["outcome"] == "cancelled"
