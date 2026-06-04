"""Integration tests for loop isolation from daemon API (IG-408).

These tests verify that loops are properly isolated with:
- No event leakage between different loops
- No message leakage during concurrent execution
- Loop-scoped cancellation isolation
- Thread checkpoint isolation per loop workspace
- Proper event sharing for multiple clients on same loop
- Subscription lifecycle isolation (detach, reattach)
- Workspace isolation (loop_new, loop_delete)
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from soothe.core.loop.state.persistence.directory_manager import (
    PersistenceDirectoryManager,
)

from soothe_daemon import SootheDaemon, WebSocketClient

from ..daemon_fixtures import (
    alloc_ephemeral_port,
    await_event_type,
    await_status_state,
    build_daemon_config,
    force_isolated_home,
    integration_llm_idle_timeout,
    websocket_bootstrap_loop_session,
    websocket_create_loop_only,
)


async def _connect_and_drain_handshake(client: WebSocketClient) -> None:
    """Connect and wait until daemon handshake is complete."""
    await client.connect()
    await client.wait_for_daemon_ready()


async def _clear_pending_and_subscribe(client: WebSocketClient, loop_id: str) -> None:
    """Clear pending events from setup phase, then verify subscription."""
    # The WebSocketClient accumulates pending events during setup (daemon_ready,
    # status, loop_new_response, etc.). Clear them before isolation checks.
    client.clear_pending_events()
    # Wait for subscription confirmation to ensure clean state
    await client.request_response(
        {"type": "loop_subscribe", "loop_id": loop_id},
        response_type="loop_subscribe_response",
        timeout=5.0,
    )


async def _create_client_with_loop(ws_port: int) -> tuple[WebSocketClient, str]:
    """Helper: create client and bootstrap loop; returns (client, loop_id)."""
    client = WebSocketClient(url=f"ws://127.0.0.1:{ws_port}")
    await _connect_and_drain_handshake(client)
    loop_id = await websocket_bootstrap_loop_session(client)
    return client, loop_id


@pytest.mark.asyncio
@pytest.mark.integration
class TestLoopIsolation:
    """Integration tests verifying loop isolation from daemon API."""

    # -------------------------------------------------------------------------
    # Test 1: Concurrent Loops - No Event Leakage
    # -------------------------------------------------------------------------

    async def test_concurrent_loops_no_event_leakage(self, tmp_path: Path):
        """Two clients subscribed to different loops execute concurrently;
        verify no cross-loop event leakage.
        """
        force_isolated_home(tmp_path / "soothe-home")
        ws_port = alloc_ephemeral_port()
        config, daemon_cfg = build_daemon_config(tmp_path, websocket_port=ws_port)

        daemon = SootheDaemon(config, daemon_config=daemon_cfg, handle_sigint_shutdown=False)
        await daemon.start()
        await asyncio.sleep(0.3)

        try:
            # Create two clients with different loops
            client1, loop1 = await _create_client_with_loop(ws_port)
            client2, loop2 = await _create_client_with_loop(ws_port)
            assert loop1 != loop2, "Loops must have different IDs"

            # Send input to both loops concurrently
            await asyncio.gather(
                client1.send_input(loop1, "Query from loop1"),
                client2.send_input(loop2, "Query from loop2"),
            )

            # Verify client1 only receives loop1 events (or global events without loop_id)
            events1 = []
            for _ in range(5):  # Collect several events
                event = await asyncio.wait_for(client1.read_event(), timeout=2.0)
                if event:
                    events1.append(event)
                    # Events with loop_id should match loop1
                    if event.get("loop_id"):
                        assert event.get("loop_id") == loop1, (
                            f"Client1 received event from wrong loop: {event.get('loop_id')}"
                        )

            # Verify client2 only receives loop2 events (or global events without loop_id)
            events2 = []
            for _ in range(5):  # Collect several events
                event = await asyncio.wait_for(client2.read_event(), timeout=2.0)
                if event:
                    events2.append(event)
                    # Events with loop_id should match loop2
                    if event.get("loop_id"):
                        assert event.get("loop_id") == loop2, (
                            f"Client2 received event from wrong loop: {event.get('loop_id')}"
                        )

            # Verify no cross-contamination of loop-specific events
            loop_ids_in_client1 = {e.get("loop_id") for e in events1 if e.get("loop_id")}
            loop_ids_in_client2 = {e.get("loop_id") for e in events2 if e.get("loop_id")}

            assert loop_ids_in_client1 == {loop1}, "Client1 should only see loop1-specific events"
            assert loop_ids_in_client2 == {loop2}, "Client2 should only see loop2-specific events"

            await client1.close()
            await client2.close()
        finally:
            await daemon.stop()

    # -------------------------------------------------------------------------
    # Test 2: Concurrent Loops - No Message Leakage
    # -------------------------------------------------------------------------

    async def test_concurrent_loops_no_message_leakage(self, tmp_path: Path):
        """Verify input messages don't leak between loops during concurrent execution."""
        force_isolated_home(tmp_path / "soothe-home")
        ws_port = alloc_ephemeral_port()
        config, daemon_cfg = build_daemon_config(tmp_path, websocket_port=ws_port)

        daemon = SootheDaemon(config, daemon_config=daemon_cfg, handle_sigint_shutdown=False)
        await daemon.start()
        await asyncio.sleep(0.3)

        try:
            # Create two clients with different loops
            client1, loop1 = await _create_client_with_loop(ws_port)
            client2, loop2 = await _create_client_with_loop(ws_port)

            # Clear pending events only for client2 before isolation check
            # Client2 should not receive any loop1 events during execution
            client2.clear_pending_events()

            # Send multiple inputs to loop1 while loop2 is idle
            for i in range(3):
                await client1.send_input(loop1, f"Message {i} to loop1")

            # Verify loop1 processes inputs correctly
            events1_count = 0
            for _ in range(10):
                event = await asyncio.wait_for(client1.read_event(), timeout=1.0)
                if event and event.get("type") in ("status", "event"):
                    events1_count += 1
                    # Events with loop_id should match loop1
                    if event.get("loop_id"):
                        assert event.get("loop_id") == loop1

            assert events1_count > 0, "Loop1 should have processed messages"

            # Verify loop2 client receives NO events from loop1 (isolation)
            with pytest.raises((asyncio.TimeoutError, asyncio.CancelledError)):
                # Try to read from client2 - should timeout (no events)
                await asyncio.wait_for(client2.read_event(), timeout=0.5)

            await client1.close()
            await client2.close()
        finally:
            await daemon.stop()

    # -------------------------------------------------------------------------
    # Test 3: Loop-Scoped Cancellation Isolation
    # -------------------------------------------------------------------------

    async def test_loop_scoped_cancellation_isolation(self, tmp_path: Path):
        """Cancel one loop without affecting other running loops."""
        force_isolated_home(tmp_path / "soothe-home")
        ws_port = alloc_ephemeral_port()
        config, daemon_cfg = build_daemon_config(tmp_path, websocket_port=ws_port)

        daemon = SootheDaemon(config, daemon_config=daemon_cfg, handle_sigint_shutdown=False)
        await daemon.start()
        await asyncio.sleep(0.3)

        try:
            # Create two clients with different loops
            client1, loop1 = await _create_client_with_loop(ws_port)
            client2, loop2 = await _create_client_with_loop(ws_port)

            # Start a long-running execution on loop1 only; do not run loop2 until
            # after cancel so two checkpointers never contend on SQLite.
            await client1.send_input(loop1, "Count to 100 slowly")
            await await_status_state(client1.read_event, "running", timeout=10.0)

            # Cancel loop1 via /cancel (handled in message_router; no cancel_response RPC)
            await client1.send_command("/cancel")

            # Verify loop1 execution stops (goes to idle/cancelled)
            await await_status_state(
                client1.read_event, {"idle", "cancelled", "stopped"}, timeout=15.0
            )

            # loop2 should still accept work after loop1 is cancelled
            await client2.send_input(loop2, "Reply with only: OK-after-cancel")
            post = await await_status_state(
                client2.read_event, {"running", "idle"}, timeout=integration_llm_idle_timeout()
            )
            if post.get("state") == "running":
                await await_status_state(
                    client2.read_event, "idle", timeout=integration_llm_idle_timeout()
                )

            await client1.close()
            await client2.close()
        finally:
            await daemon.stop()

    # -------------------------------------------------------------------------
    # Test 4: Thread Checkpoint Isolation Per Loop
    # -------------------------------------------------------------------------

    async def test_thread_checkpoint_isolation_per_loop(self, tmp_path: Path):
        """Verify thread checkpoints are isolated per loop workspace."""
        force_isolated_home(tmp_path / "soothe-home")
        ws_port = alloc_ephemeral_port()
        config, daemon_cfg = build_daemon_config(tmp_path, websocket_port=ws_port)

        daemon = SootheDaemon(config, daemon_config=daemon_cfg, handle_sigint_shutdown=False)
        await daemon.start()
        await asyncio.sleep(0.3)

        try:
            # Create two clients with different loops
            client1, loop1 = await _create_client_with_loop(ws_port)
            client2, loop2 = await _create_client_with_loop(ws_port)

            # Execute on both loops to create checkpoints
            await client1.send_input(loop1, "Create checkpoint in loop1")
            await asyncio.wait_for(client1.read_event(), timeout=2.0)

            await client2.send_input(loop2, "Create checkpoint in loop2")
            await asyncio.wait_for(client2.read_event(), timeout=2.0)

            # Get loop_tree for each loop
            tree1_resp = await client1.request_response(
                {"type": "loop_tree", "loop_id": loop1},
                response_type="loop_tree_response",
                timeout=5.0,
            )

            tree2_resp = await client2.request_response(
                {"type": "loop_tree", "loop_id": loop2},
                response_type="loop_tree_response",
                timeout=5.0,
            )

            # Verify loop1 tree contains only loop1 threads
            tree1_threads = tree1_resp.get("threads", [])
            for thread in tree1_threads:
                thread_loop = daemon._thread_registry.get_thread_loop(thread.get("thread_id"))
                # Thread should be associated with loop1
                # Note: If thread_id not in registry, check metadata
                if thread_loop:
                    assert thread_loop == loop1, "Thread in loop1 tree belongs to wrong loop"

            # Verify loop2 tree contains only loop2 threads
            tree2_threads = tree2_resp.get("threads", [])
            for thread in tree2_threads:
                thread_loop = daemon._thread_registry.get_thread_loop(thread.get("thread_id"))
                if thread_loop:
                    assert thread_loop == loop2, "Thread in loop2 tree belongs to wrong loop"

            # Verify metadata files in loop directories are separate
            loop1_dir = PersistenceDirectoryManager.get_loop_directory(loop1)
            loop2_dir = PersistenceDirectoryManager.get_loop_directory(loop2)

            assert loop1_dir != loop2_dir, "Loop directories must be separate"
            assert loop1_dir.exists(), "Loop1 directory should exist"
            assert loop2_dir.exists(), "Loop2 directory should exist"

            # Check metadata is independent via DB
            metadata1 = await daemon._persistence_manager.get_loop_metadata(loop1)
            metadata2 = await daemon._persistence_manager.get_loop_metadata(loop2)

            assert metadata1 is not None, "Loop1 metadata should exist in DB"
            assert metadata2 is not None, "Loop2 metadata should exist in DB"
            assert metadata1.get("loop_id") == loop1
            assert metadata2.get("loop_id") == loop2

            await client1.close()
            await client2.close()
        finally:
            await daemon.stop()

    # -------------------------------------------------------------------------
    # Test 5: Multiple Clients Same Loop Share Events
    # -------------------------------------------------------------------------

    async def test_multiple_clients_same_loop_share_events(self, tmp_path: Path):
        """Multiple clients subscribed to same loop should all receive loop events."""
        force_isolated_home(tmp_path / "soothe-home")
        ws_port = alloc_ephemeral_port()
        config, daemon_cfg = build_daemon_config(tmp_path, websocket_port=ws_port)

        daemon = SootheDaemon(config, daemon_config=daemon_cfg, handle_sigint_shutdown=False)
        await daemon.start()
        await asyncio.sleep(0.3)

        try:
            # Create first client and loop
            client1, loop_id = await _create_client_with_loop(ws_port)

            # Create two more clients and subscribe to SAME loop
            client2 = WebSocketClient(url=f"ws://127.0.0.1:{ws_port}")
            await _connect_and_drain_handshake(client2)
            sub2_resp = await client2.request_response(
                {"type": "loop_subscribe", "loop_id": loop_id},
                response_type="loop_subscribe_response",
                timeout=5.0,
            )
            assert sub2_resp.get("success", True), "Client2 should subscribe to loop"

            client3 = WebSocketClient(url=f"ws://127.0.0.1:{ws_port}")
            await _connect_and_drain_handshake(client3)
            sub3_resp = await client3.request_response(
                {"type": "loop_subscribe", "loop_id": loop_id},
                response_type="loop_subscribe_response",
                timeout=5.0,
            )
            assert sub3_resp.get("success", True), "Client3 should subscribe to loop"

            # Send input to that loop from any client
            await client1.send_input(loop_id, "Test message to shared loop")

            # Verify ALL three clients receive the events
            received = []
            for client_name, client in [
                ("client1", client1),
                ("client2", client2),
                ("client3", client3),
            ]:
                event = await asyncio.wait_for(client.read_event(), timeout=2.0)
                if event:
                    received.append((client_name, event))
                    # Events with loop_id should match the shared loop
                    if event.get("loop_id"):
                        assert event.get("loop_id") == loop_id, (
                            f"{client_name} received event from wrong loop"
                        )

            assert len(received) >= 3, "All three clients should receive events"

            # Verify loop-specific event content is consistent (same loop_id)
            for client_name, event in received:
                if event.get("loop_id"):
                    assert event.get("loop_id") == loop_id

            await client1.close()
            await client2.close()
            await client3.close()
        finally:
            await daemon.stop()

    # -------------------------------------------------------------------------
    # Test 6: Loop Detach Removes Subscription
    # -------------------------------------------------------------------------

    async def test_loop_detach_removes_subscription(self, tmp_path: Path):
        """Client detaching from loop stops receiving loop events."""
        force_isolated_home(tmp_path / "soothe-home")
        ws_port = alloc_ephemeral_port()
        config, daemon_cfg = build_daemon_config(tmp_path, websocket_port=ws_port)

        daemon = SootheDaemon(config, daemon_config=daemon_cfg, handle_sigint_shutdown=False)
        await daemon.start()
        await asyncio.sleep(0.3)

        try:
            # Create two clients subscribed to same loop
            client1, loop_id = await _create_client_with_loop(ws_port)
            client2 = WebSocketClient(url=f"ws://127.0.0.1:{ws_port}")
            await _connect_and_drain_handshake(client2)
            await client2.request_response(
                {"type": "loop_subscribe", "loop_id": loop_id},
                response_type="loop_subscribe_response",
                timeout=5.0,
            )

            # Clear pending events from setup phase before detach test
            client1.clear_pending_events()
            client2.clear_pending_events()

            # Client1 detaches from loop
            detach_resp = await client1.request_response(
                {"type": "loop_detach", "loop_id": loop_id},
                response_type="loop_detach_response",
                timeout=5.0,
            )
            assert detach_resp.get("success", True), "Detach should succeed"

            # Clear any events from detach response handling
            client1.clear_pending_events()

            # Send input to loop from client2
            await client2.send_input(loop_id, "Test after detach")

            # Verify client1 receives NO events (timeout)
            with pytest.raises((asyncio.TimeoutError, asyncio.CancelledError)):
                await asyncio.wait_for(client1.read_event(), timeout=0.5)

            # Verify client2 still receives events
            event = await asyncio.wait_for(client2.read_event(), timeout=2.0)
            assert event is not None
            # Events with loop_id should match loop_id
            if event.get("loop_id"):
                assert event.get("loop_id") == loop_id

            await client1.close()
            await client2.close()
        finally:
            await daemon.stop()

    # -------------------------------------------------------------------------
    # Test 7: Loop Reattach Replay Isolation
    # -------------------------------------------------------------------------

    async def test_loop_reattach_replay_isolation(self, tmp_path: Path):
        """Reattaching to loop replays history without leaking to other loops."""
        force_isolated_home(tmp_path / "soothe-home")
        ws_port = alloc_ephemeral_port()
        config, daemon_cfg = build_daemon_config(tmp_path, websocket_port=ws_port)

        daemon = SootheDaemon(config, daemon_config=daemon_cfg, handle_sigint_shutdown=False)
        await daemon.start()
        await asyncio.sleep(0.3)

        try:
            # Create first client/loop and run one turn before attaching a second loop so
            # two LLM workers are not starting checkpoints at the same instant.
            client1, loop1 = await _create_client_with_loop(ws_port)

            # Client1 executes on loop1 (creates event history)
            await client1.send_input(loop1, "First message in loop1")
            st = await await_status_state(
                client1.read_event, {"running", "idle"}, timeout=integration_llm_idle_timeout()
            )
            if st.get("state") == "running":
                await await_status_state(
                    client1.read_event, "idle", timeout=integration_llm_idle_timeout()
                )

            client2 = WebSocketClient(url=f"ws://127.0.0.1:{ws_port}")
            await _connect_and_drain_handshake(client2)
            loop2 = await websocket_bootstrap_loop_session(client2)
            _ = loop2  # second loop id for isolation context; not driven in this scenario

            # Clear handshake/setup events; client2 was not connected during loop1's turn.
            client2.clear_pending_events()

            # No backlog delivered to client2 for loop1's history
            with pytest.raises((asyncio.TimeoutError, asyncio.CancelledError)):
                await asyncio.wait_for(client2.read_event(), timeout=0.5)

            # Client1 detaches from loop1
            await client1.request_response(
                {"type": "loop_detach", "loop_id": loop1},
                response_type="loop_detach_response",
                timeout=5.0,
            )

            # Client1 reattaches to loop1 with replay (RFC-411: history_replay + markers)
            client1.clear_pending_events()
            await client1.send_loop_reattach(loop1)
            await await_event_type(
                client1.read_event, "history_replay", timeout=integration_llm_idle_timeout()
            )
            await await_event_type(client1.read_event, "loop_reattached", timeout=15.0)
            await await_event_type(client1.read_event, "replay_complete", timeout=15.0)

            # Verify replay events go only to client1 (already consumed above)

            # Verify client2 never receives loop1 replay events
            with pytest.raises((asyncio.TimeoutError, asyncio.CancelledError)):
                await asyncio.wait_for(client2.read_event(), timeout=1.0)

            await client1.close()
            await client2.close()
        finally:
            await daemon.stop()

    # -------------------------------------------------------------------------
    # Test 8: Loop New Creates Isolated Workspace
    # -------------------------------------------------------------------------

    async def test_loop_new_creates_isolated_workspace(self, tmp_path: Path):
        """Each loop_new creates isolated metadata workspace."""
        force_isolated_home(tmp_path / "soothe-home")
        ws_port = alloc_ephemeral_port()
        config, daemon_cfg = build_daemon_config(tmp_path, websocket_port=ws_port)

        daemon = SootheDaemon(config, daemon_config=daemon_cfg, handle_sigint_shutdown=False)
        await daemon.start()
        await asyncio.sleep(0.3)

        try:
            client = WebSocketClient(url=f"ws://127.0.0.1:{ws_port}")
            await _connect_and_drain_handshake(client)

            # Create two loops
            loop1 = await websocket_create_loop_only(client)
            loop2 = await websocket_create_loop_only(client)

            # Verify loop_ids are unique (UUID7)
            assert loop1 != loop2, "Loop IDs must be unique"

            # Verify loop directories created separately
            loop1_dir = PersistenceDirectoryManager.get_loop_directory(loop1)
            loop2_dir = PersistenceDirectoryManager.get_loop_directory(loop2)

            assert loop1_dir != loop2_dir, "Loop directories must be separate"
            assert loop1_dir.exists(), "Loop1 directory should exist"
            assert loop2_dir.exists(), "Loop2 directory should exist"

            # Check metadata is independent via DB
            metadata1 = await daemon._persistence_manager.get_loop_metadata(loop1)
            metadata2 = await daemon._persistence_manager.get_loop_metadata(loop2)

            assert metadata1 is not None, "Loop1 metadata should exist in DB"
            assert metadata2 is not None, "Loop2 metadata should exist in DB"

            # Verify metadata is independent
            assert metadata1.get("loop_id") == loop1
            assert metadata2.get("loop_id") == loop2
            assert metadata1.get("loop_id") != metadata2.get("loop_id")

            # Verify thread_ids lists start empty
            assert metadata1.get("thread_ids", []) == []
            assert metadata2.get("thread_ids", []) == []

            await client.close()
        finally:
            await daemon.stop()

    # -------------------------------------------------------------------------
    # Test 9: Loop List Returns Only Owned Loops
    # -------------------------------------------------------------------------

    async def test_loop_list_isolation(self, tmp_path: Path):
        """loop_list RPC returns all loops without cross-contamination."""
        force_isolated_home(tmp_path / "soothe-home")
        ws_port = alloc_ephemeral_port()
        config, daemon_cfg = build_daemon_config(tmp_path, websocket_port=ws_port)

        daemon = SootheDaemon(config, daemon_config=daemon_cfg, handle_sigint_shutdown=False)
        await daemon.start()
        await asyncio.sleep(0.3)

        try:
            # Create two clients with multiple loops each
            client1 = WebSocketClient(url=f"ws://127.0.0.1:{ws_port}")
            await _connect_and_drain_handshake(client1)
            loop1a = await websocket_create_loop_only(client1)
            loop1b = await websocket_create_loop_only(client1)

            client2 = WebSocketClient(url=f"ws://127.0.0.1:{ws_port}")
            await _connect_and_drain_handshake(client2)
            loop2a = await websocket_create_loop_only(client2)

            # Both clients call loop_list
            list1_resp = await client1.request_response(
                {"type": "loop_list", "limit": 20},
                response_type="loop_list_response",
                timeout=5.0,
            )

            list2_resp = await client2.request_response(
                {"type": "loop_list", "limit": 20},
                response_type="loop_list_response",
                timeout=5.0,
            )

            # Verify both see all loops (loop_list is global, not per-client)
            loops1 = {loop["loop_id"] for loop in list1_resp.get("loops", [])}
            loops2 = {loop["loop_id"] for loop in list2_resp.get("loops", [])}

            all_loops = {loop1a, loop1b, loop2a}
            # loop_list is global: both clients see the same catalog, which may include
            # loops from earlier integration runs if persistence is shared.
            assert all_loops <= loops1, "Client1 should include all loops created in this test"
            assert all_loops <= loops2, "Client2 should include all loops created in this test"
            assert loops1 == loops2, "Both clients should see the same loop_list snapshot"

            await client1.close()
            await client2.close()
        finally:
            await daemon.stop()

    # -------------------------------------------------------------------------
    # Test 10: Loop Delete Isolation
    # -------------------------------------------------------------------------

    async def test_loop_delete_isolation(self, tmp_path: Path):
        """Deleting one loop doesn't affect other loops."""
        force_isolated_home(tmp_path / "soothe-home")
        ws_port = alloc_ephemeral_port()
        config, daemon_cfg = build_daemon_config(tmp_path, websocket_port=ws_port)

        daemon = SootheDaemon(config, daemon_config=daemon_cfg, handle_sigint_shutdown=False)
        await daemon.start()
        await asyncio.sleep(0.3)

        try:
            # Create two loops — no need to execute LLM turns; the isolation
            # property under test is directory/metadata independence.
            client1, loop1 = await _create_client_with_loop(ws_port)
            client2, loop2 = await _create_client_with_loop(ws_port)

            # Verify both loops exist in DB before deletion
            metadata1 = await daemon._persistence_manager.get_loop_metadata(loop1)
            metadata2 = await daemon._persistence_manager.get_loop_metadata(loop2)
            assert metadata1 is not None and metadata1.get("loop_id") == loop1
            assert metadata2 is not None and metadata2.get("loop_id") == loop2

            # Delete loop1
            delete_resp = await client1.request_response(
                {"type": "loop_delete", "loop_id": loop1},
                response_type="loop_delete_response",
                timeout=10.0,
            )
            assert delete_resp.get("success", True), "Delete should succeed"

            # Verify loop1 directory removed
            loop1_dir = PersistenceDirectoryManager.get_loop_directory(loop1)
            assert not loop1_dir.exists(), "Loop1 directory should be deleted"

            # Verify loop2 directory intact
            loop2_dir = PersistenceDirectoryManager.get_loop_directory(loop2)
            assert loop2_dir.exists(), "Loop2 directory should still exist"

            # Verify loop2 metadata unchanged in DB
            metadata2_after = await daemon._persistence_manager.get_loop_metadata(loop2)
            assert metadata2_after is not None, "Loop2 metadata should still be in DB"
            assert metadata2_after.get("loop_id") == loop2, "Loop2 metadata should be intact"

            await client1.close()
            await client2.close()
        finally:
            await daemon.stop()
