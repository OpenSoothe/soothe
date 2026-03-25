"""Standalone execution for headless mode."""

import json
import logging
import sys
from typing import Any

from soothe.config import SootheConfig
from soothe.core.event_catalog import CHITCHAT_RESPONSE, FINAL_REPORT
from soothe.ux.shared.message_processing import (
    MessageProcessor,
    OutputFormatter,
    SharedState,
    is_multi_step_plan,
    strip_internal_tags,
)

logger = logging.getLogger(__name__)


class _CliOutputFormatter(OutputFormatter):
    """CLI output formatter for headless mode."""

    def __init__(self) -> None:
        """Initialize CLI output formatter."""
        self.needs_stdout_newline = False

    def emit_assistant_text(self, text: str, *, is_main: bool) -> None:  # noqa: ARG002
        """Emit assistant text to stdout.

        Args:
            text: The assistant text to emit.
            is_main: Whether this is from the main agent (unused in CLI).
        """
        sys.stdout.write(text)
        sys.stdout.flush()
        self.needs_stdout_newline = True

    def emit_tool_call(self, name: str, *, prefix: str | None, is_main: bool) -> None:  # noqa: ARG002
        """Emit a tool call notification to stderr.

        Args:
            name: The tool name being called.
            prefix: Optional namespace prefix for subagents.
            is_main: Whether this is from the main agent (unused in CLI).
        """
        # Add newline before stderr output if needed
        if self.needs_stdout_newline:
            sys.stdout.write("\n")
            sys.stdout.flush()
            self.needs_stdout_newline = False

        if prefix:
            sys.stderr.write(f"[{prefix}] [tool] Calling: {name}\n")
        else:
            sys.stderr.write(f"[tool] Calling: {name}\n")
        sys.stderr.flush()

    def emit_tool_result(self, tool_name: str, brief: str, *, prefix: str | None, is_main: bool) -> None:  # noqa: ARG002
        """Emit a tool result notification to stderr.

        Args:
            tool_name: The tool name that produced the result.
            brief: Brief summary of the result.
            prefix: Optional namespace prefix for subagents.
            is_main: Whether this is from the main agent (unused in CLI).
        """
        # Add newline before stderr output if needed
        if self.needs_stdout_newline:
            sys.stdout.write("\n")
            sys.stdout.flush()
            self.needs_stdout_newline = False

        if prefix:
            sys.stderr.write(f"[{prefix}] [tool] Result ({tool_name}): {brief}\n")
        else:
            sys.stderr.write(f"[tool] Result ({tool_name}): {brief}\n")
        sys.stderr.flush()


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
    from langchain_core.messages import AIMessage, ToolMessage

    from soothe.core.runner import SootheRunner
    from soothe.daemon.thread_logger import ThreadLogger
    from soothe.ux.cli.rendering import render_progress_event
    from soothe.ux.shared.progress_verbosity import classify_custom_event, should_show
    from soothe.ux.shared.rendering import resolve_namespace_label

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

    # Use shared state and message processor
    state = SharedState()
    formatter = _CliOutputFormatter()
    processor = MessageProcessor(state, formatter)

    verbosity = cfg.logging.progress_verbosity

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
                        state.full_response.append(report_text)
                    # Reset multi-step flag after final report
                    state.multi_step_active = False
                elif etype == CHITCHAT_RESPONSE:
                    chitchat_content = data.get("content", "")
                    if chitchat_content:
                        # Strip internal tags for clean display
                        cleaned = strip_internal_tags(chitchat_content)
                        if cleaned:
                            sys.stdout.write(cleaned)
                            sys.stdout.write("\n")
                            sys.stdout.flush()
                            state.full_response.append(cleaned)
                else:
                    # Check for multi-step plan creation
                    if is_multi_step_plan(data):
                        state.multi_step_active = True
                    category = classify_custom_event(namespace, data)
                    if should_show(category, verbosity):
                        # Add newline before stderr output if needed
                        if formatter.needs_stdout_newline:
                            sys.stdout.write("\n")
                            sys.stdout.flush()
                            formatter.needs_stdout_newline = False
                        prefix = resolve_namespace_label(namespace, state.name_map) if namespace else None
                        render_progress_event(data, prefix=prefix, verbosity=verbosity)
                    if category == "error":
                        state.has_error = True

            if mode == "messages":
                if not isinstance(data, tuple) or len(data) != _msg_pair_len:
                    continue
                msg, metadata = data
                is_main = not namespace
                if metadata and metadata.get("lc_source") == "summarization":
                    continue

                # Use shared message processor
                if isinstance(msg, AIMessage):
                    processor.process_ai_message(msg, is_main=is_main, verbosity=verbosity)
                elif isinstance(msg, ToolMessage):
                    prefix = resolve_namespace_label(namespace, state.name_map) if namespace else None
                    processor.process_tool_message(msg, prefix=prefix, verbosity=verbosity)

        if state.full_response:
            if formatter.needs_stdout_newline:
                sys.stdout.write("\n")
                sys.stdout.flush()
            thread_logger.log_assistant_response("".join(state.full_response))
        return 1 if state.has_error else 0
    finally:
        await runner.cleanup()

    return exit_code
