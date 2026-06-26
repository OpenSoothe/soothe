"""Loop reattachment handler — card-ledger replay (RFC-413).

When a client (re)subscribes to an existing loop, the daemon streams the
bound display-card ledger through ``card.*`` wire frames. Clients on the
new wire (TUI, soothe-desktop) render directly from those frames.

RFC-411's ``history_replay`` / ``loop_reattached`` / ``replay_complete``
frames were removed when this RFC superseded it, along with the
reconstructor / enricher modules under ``soothe.core.events.replay``.
Clients that still expect those frames should upgrade to consume
``card.*``.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

logger = logging.getLogger(__name__)


async def handle_loop_reattach(
    loop_id: str,
    daemon: Any,
    client_id: Any,
) -> None:
    """Handle loop (re)attachment by streaming bound cards from the ledger.

    Process:
    1. Ensure the daemon's card ledger for this loop is populated (eagerly
       backfill from checkpoint + activity log if needed).
    2. Stream ``card.replay_begin`` → ``card.created`` × N → ``card.replay_end``.

    Args:
        loop_id: StrangeLoop identifier.
        daemon: Daemon instance (for sending messages + card manager access).
        client_id: Client connection identifier.
    """
    try:
        logger.info("Handling loop reattachment for %s (client=%s)", loop_id, client_id)

        card_manager = getattr(daemon, "_card_manager", None)
        if card_manager is None:
            logger.warning(
                "Card manager unavailable; reattach for %s will emit empty replay",
                loop_id,
            )
            return

        async def _send(frame: dict[str, Any]) -> None:
            await daemon._send_client_message(client_id, frame)

        card_count = await card_manager.replay_to_client(str(loop_id), _send)

        logger.info(
            "Loop reattachment complete: %s (%d cards replayed)",
            loop_id,
            card_count,
        )

    except Exception as exc:
        logger.error(
            "Failed to handle loop reattachment for %s: %s", loop_id, str(exc), exc_info=True
        )
        await daemon._send_client_message(
            client_id,
            {
                "type": "error",
                "code": "LOOP_REATTACH_FAILED",
                "message": f"Failed to reconstruct loop history: {exc!s}",
                "loop_id": loop_id,
            },
        )


def schedule_loop_reattach(
    loop_id: str,
    daemon: Any,
    client_id: Any,
) -> asyncio.Task[None]:
    """Schedule card replay after ``loop_subscribe`` without blocking the RPC.

    The subscribe response is sent first so clients (TUI) can leave the
    connecting state immediately. Card frames stream afterward on the same
    client connection.
    """

    async def _run() -> None:
        try:
            await handle_loop_reattach(loop_id, daemon, client_id)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception(
                "Background loop reattachment failed for %s (client=%s)",
                loop_id,
                client_id,
            )

    return asyncio.create_task(_run(), name=f"loop-reattach-{str(loop_id)[:8]}")


__all__ = ["handle_loop_reattach", "schedule_loop_reattach"]
