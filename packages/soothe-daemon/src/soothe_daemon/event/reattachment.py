"""Loop reattachment handler — card-ledger replay."""

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
    """Handle loop (re)attachment by streaming bound cards from the ledger."""
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
    """Schedule card replay after `loop_subscribe` without blocking the RPC."""

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
