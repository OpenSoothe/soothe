"""Standalone execution for headless mode."""

import json
import logging
import sys
from typing import Any

from soothe.cli.rendering.tool_brief import extract_tool_brief as _headless_tool_brief
from soothe.config import SootheConfig
from soothe.core.events import CHITCHAT_RESPONSE, FINAL_REPORT

logger = logging.getLogger(__name__)


async def run_headless_standalone(
    cfg: SootheConfig,
    prompt: str,
    *,
    thread_id: str | None = None,
    output_format: str = "text",
    autonomous: bool = False,
    max_iterations: int | None = None,
) -> int:
    """Run a single prompt in standalone mode (no daemon)."""
    from langchain_core.messages import AIMessage, AIMessageChunk, ToolMessage

    from soothe.cli.progress_verbosity import classify_custom_event, should_show
    from soothe.cli.rendering import render_progress_event
    from soothe.cli.thread_logger import ThreadLogger
    from soothe.cli.tui_shared import resolve_namespace_label, update_name_map_from_tool_calls
    from soothe.core.runner import SootheRunner

    runner = SootheRunner(cfg)
    thread_logger = ThreadLogger(
        thread_dir=cfg.logging.thread_logging.dir,
        thread_id=thread_id or "headless",
        retention_days=cfg.logging.thread_logging.retention_days,
        max_size_mb=cfg.logging.thread_logging.max_size_mb,
    )

    _chunk_len = 3
    _msg_pair_len = 2
    exit_code = 0

    full_response: list[str] = []
    seen_message_ids: set[str] = set()
    name_map: dict[str, str] = {}
    has_error = False
    verbosity = cfg.logging.progress_verbosity
    needs_stdout_newline = False  # Track if we need a newline before stderr output

    thread_logger.log_user_input(prompt)

    stream_kwargs: dict[str, Any] = {"thread_id": thread_id}
    if autonomous:
        stream_kwargs["autonomous"] = True
        if max_iterations is not None:
            stream_kwargs["max_iterations"] = max_iterations

    try:
        async for chunk in runner.astream(prompt, **stream_kwargs):
            if not isinstance(chunk, tuple) or len(chunk) != _chunk_len:
                continue
            namespace, mode, data = chunk

            thread_logger.log(namespace, mode, data)

            if output_format == "jsonl":
                sys.stdout.write(
                    json.dumps({"namespace": list(namespace), "mode": mode, "data": data}, default=str) + "\n"
                )
                sys.stdout.flush()
                continue

            if mode == "custom" and isinstance(data, dict):
                etype = str(data.get("type", ""))

                if etype == FINAL_REPORT:
                    report_text = data.get("summary", "")
                    if report_text:
                        sys.stdout.write("\n\n")
                        sys.stdout.write(report_text)
                        sys.stdout.write("\n")
                        sys.stdout.flush()
                        full_response.append(report_text)
                elif etype == CHITCHAT_RESPONSE:
                    chitchat_content = data.get("content", "")
                    if chitchat_content:
                        sys.stdout.write(chitchat_content)
                        sys.stdout.write("\n")
                        sys.stdout.flush()
                        full_response.append(chitchat_content)
                else:
                    category = classify_custom_event(namespace, data)
                    if should_show(category, verbosity):
                        # Add newline before stderr output if needed
                        if needs_stdout_newline:
                            sys.stdout.write("\n")
                            sys.stdout.flush()
                            needs_stdout_newline = False
                        prefix = resolve_namespace_label(namespace, name_map) if namespace else None
                        render_progress_event(data, prefix=prefix, verbosity=verbosity)
                    if category == "error":
                        has_error = True

            if mode == "messages":
                if not isinstance(data, tuple) or len(data) != _msg_pair_len:
                    continue
                msg, metadata = data
                is_main = not namespace
                if metadata and metadata.get("lc_source") == "summarization":
                    continue
                if isinstance(msg, AIMessage) and hasattr(msg, "content_blocks"):
                    update_name_map_from_tool_calls(msg, name_map)
                    msg_id = msg.id or ""
                    if not isinstance(msg, AIMessageChunk):
                        if msg_id in seen_message_ids:
                            continue
                        seen_message_ids.add(msg_id)
                    elif msg_id:
                        seen_message_ids.add(msg_id)
                    for block in msg.content_blocks:
                        if not isinstance(block, dict):
                            continue
                        btype = block.get("type")
                        if btype == "text":
                            text = block.get("text", "")
                            if is_main and text and should_show("assistant_text", verbosity):
                                sys.stdout.write(text)
                                sys.stdout.flush()
                                full_response.append(text)
                                needs_stdout_newline = True
                        elif btype in ("tool_call", "tool_call_chunk") and should_show("tool_activity", verbosity):
                            name = block.get("name", "")
                            if name:
                                # Add newline before stderr output if needed
                                if needs_stdout_newline:
                                    sys.stdout.write("\n")
                                    sys.stdout.flush()
                                    needs_stdout_newline = False
                                prefix = resolve_namespace_label(namespace, name_map) if namespace else None
                                if prefix:
                                    sys.stderr.write(f"[{prefix}] [tool] Calling: {name}\n")
                                else:
                                    sys.stderr.write(f"[tool] Calling: {name}\n")
                                sys.stderr.flush()
                elif isinstance(msg, ToolMessage) and should_show("tool_activity", verbosity):
                    tool_name = getattr(msg, "name", "tool")
                    content = msg.content if isinstance(msg.content, str) else str(msg.content)
                    brief = _headless_tool_brief(tool_name, content)
                    # Add newline before stderr output if needed
                    if needs_stdout_newline:
                        sys.stdout.write("\n")
                        sys.stdout.flush()
                        needs_stdout_newline = False
                    prefix = resolve_namespace_label(namespace, name_map) if namespace else None
                    if prefix:
                        sys.stderr.write(f"[{prefix}] [tool] Result ({tool_name}): {brief}\n")
                    else:
                        sys.stderr.write(f"[tool] Result ({tool_name}): {brief}\n")
                    sys.stderr.flush()
        if full_response:
            if needs_stdout_newline:
                sys.stdout.write("\n")
                sys.stdout.flush()
            thread_logger.log_assistant_response("".join(full_response))
        return 1 if has_error else 0
    finally:
        await runner.cleanup()

    return exit_code
