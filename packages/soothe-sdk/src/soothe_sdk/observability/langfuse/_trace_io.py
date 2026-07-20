"""Langfuse trace-level goal I/O patching for graph runs."""

from __future__ import annotations

import logging
from typing import Any

from soothe_sdk.observability.langfuse._merge import langfuse_handler_from_runnable_config

logger = logging.getLogger(__name__)


def _merge_trace_fields_via_ingestion(
    client: Any,
    *,
    trace_id: str,
    display_name: str,
    input_text: str,
    output_text: str,
    session_id: str | None,
) -> bool:
    """Enqueue a Langfuse ``trace-create`` merge event."""
    resources = getattr(client, "_resources", None)
    if resources is None:
        return False
    try:
        from langfuse._utils import _get_timestamp
        from langfuse.api.resources.ingestion.types.trace_body import TraceBody

        kwargs: dict[str, Any] = {
            "id": trace_id,
            "name": display_name,
            "input": input_text,
            "output": output_text,
        }
        if session_id:
            kwargs["session_id"] = session_id
        body = TraceBody(**kwargs)
        event = {
            "id": client.create_trace_id(),
            "type": "trace-create",
            "timestamp": _get_timestamp(),
            "body": body,
        }
        resources.add_trace_task(event)
        return True
    except Exception:
        logger.debug("Langfuse trace ingestion merge failed", exc_info=True)
        return False


def patch_langfuse_trace_goal_io(
    config: dict[str, Any],
    *,
    goal_text: str,
    output_text: str,
    trace_display_name: str,
    public_key: str | None = None,
    session_id: str | None = None,
) -> None:
    """Set Langfuse trace-level ``name`` / ``input`` / ``output`` for the root graph run."""
    handler = langfuse_handler_from_runnable_config(config)
    if handler is None:
        return
    trace_id = getattr(handler, "last_trace_id", None)
    if not trace_id:
        meta = config.get("metadata")
        if isinstance(meta, dict) and meta.get("langfuse_trace_id"):
            trace_id = str(meta["langfuse_trace_id"])
    if not trace_id:
        return
    try:
        from langfuse import get_client

        client = get_client(public_key=public_key) if public_key else get_client()

        merged = _merge_trace_fields_via_ingestion(
            client,
            trace_id=trace_id,
            display_name=trace_display_name,
            input_text=goal_text,
            output_text=output_text,
            session_id=session_id,
        )
        if not merged:
            span = client.start_span(
                trace_context={"trace_id": trace_id},
                name=trace_display_name,
            )
            span.update_trace(
                name=trace_display_name,
                input=goal_text,
                output=output_text,
            )
            span.end()
        client.flush()
    except Exception:
        logger.debug(
            "Langfuse trace goal I/O patch failed (non-fatal)",
            exc_info=True,
        )
