"""Standalone execution for headless mode."""

import json
import logging
import sys
import tempfile
from pathlib import Path
from typing import Any

from soothe.config import SootheConfig
from soothe.core.event_catalog import CHITCHAT_RESPONSE, FINAL_REPORT
from soothe.ux.core.message_processing import (
    MessageProcessor,
    OutputFormatter,
    SharedState,
    is_multi_step_plan,
    strip_internal_tags,
)

logger = logging.getLogger(__name__)

# Threshold for large report detection (characters)
# Reports exceeding this size are written to file instead of stdout
REPORT_STDOUT_THRESHOLD = 4000


class _CliOutputFormatter(OutputFormatter):
    """CLI output formatter for headless mode with tool call buffering.

    This formatter implements a buffering system to ensure tool calls and their
    results are displayed as matched pairs, even when tools execute in parallel
    and complete in arbitrary order.
    """

    def __init__(self) -> None:
        """Initialize CLI output formatter with buffering."""
        self.needs_stdout_newline = False
        self._recent_tool_calls: list[str] = []  # Track recent calls for duplicate suppression
        self._max_recent_calls = 10  # Keep last N tool calls

        # Buffering for tool call/result pairing
        # Maps tool_call_id -> {'name': str, 'display_str': str, 'prefix': str | None, 'emitted': bool}
        self._pending_calls: dict[str, dict[str, Any]] = {}
        # Maps tool_call_id -> result brief string
        self._pending_results: dict[str, str] = {}
        # Ordered list of tool_call_ids for sequential output
        self._call_order: list[str] = []

    def emit_assistant_text(self, text: str, *, is_main: bool) -> None:  # noqa: ARG002
        """Emit assistant text to stdout.

        Args:
            text: The assistant text to emit.
            is_main: Whether this is from the main agent (unused in CLI).
        """
        # Flush any pending tool output before assistant text
        self._flush_pending_outputs()

        sys.stdout.write(text)
        sys.stdout.flush()
        self.needs_stdout_newline = True

    def emit_tool_call(
        self,
        name: str,
        *,
        prefix: str | None,
        is_main: bool,  # noqa: ARG002
        tool_call: dict[str, Any] | None = None,
        tool_call_id: str | None = None,
    ) -> None:
        """Emit a tool call notification to stderr with tree format.

        Args:
            name: The tool name being called.
            prefix: Optional namespace prefix for subagents.
            is_main: Whether this is from the main agent (unused in CLI).
            tool_call: Optional tool call dict with args for display.
            tool_call_id: Optional unique identifier for matching with results.
        """
        # Add newline before stderr output if needed
        if self.needs_stdout_newline:
            sys.stdout.write("\n")
            sys.stdout.flush()
            self.needs_stdout_newline = False

        # Format with tree structure (see IG-053)
        from soothe.tools.display_names import get_tool_display_name
        from soothe.ux.core.message_processing import format_tool_call_args

        display_name = get_tool_display_name(name)
        args_str = format_tool_call_args(name, tool_call) if tool_call else ""

        # Duplicate suppression (see IG-053)
        call_signature = f"{display_name}{args_str}"
        if call_signature in self._recent_tool_calls:
            # Skip duplicate successive call
            return

        # Track this call
        self._recent_tool_calls.append(call_signature)
        if len(self._recent_tool_calls) > self._max_recent_calls:
            self._recent_tool_calls.pop(0)

        # Build display string
        display_str = f"[{prefix}] ⚙ {display_name}{args_str}" if prefix else f"⚙ {display_name}{args_str}"

        # If we have a tool_call_id, use buffering
        if tool_call_id:
            # Register the call
            self._pending_calls[tool_call_id] = {
                "name": name,
                "display_str": display_str,
                "prefix": prefix,
                "emitted": False,
            }
            if tool_call_id not in self._call_order:
                self._call_order.append(tool_call_id)

            # Check if result already arrived (out-of-order)
            if tool_call_id in self._pending_results:
                # Emit call + result together
                self._emit_call_result_pair(tool_call_id)
        else:
            # No ID, emit immediately (fallback behavior)
            sys.stderr.write(f"{display_str}\n")
            sys.stderr.flush()

    def emit_tool_result(
        self,
        _tool_name: str,
        brief: str,
        *,
        prefix: str | None,
        is_main: bool,  # noqa: ARG002
        tool_call_id: str | None = None,
    ) -> None:
        """Emit a tool result notification to stderr with tree format.

        Args:
            tool_name: The tool name that produced the result.
            brief: Brief summary of the result.
            prefix: Optional namespace prefix for subagents.
            is_main: Whether this is from the main agent (unused in CLI).
            tool_call_id: Optional unique identifier for matching with calls.
        """
        # Add newline before stderr output if needed
        if self.needs_stdout_newline:
            sys.stdout.write("\n")
            sys.stdout.flush()
            self.needs_stdout_newline = False

        # If we have a tool_call_id, use buffering
        if tool_call_id:
            # Check if call was already emitted
            call_info = self._pending_calls.get(tool_call_id)
            if call_info and call_info["emitted"]:
                # Call already displayed, emit result immediately
                self._emit_result(brief, prefix)
            elif call_info:
                # Call registered but not emitted yet - store result
                self._pending_results[tool_call_id] = brief
                # Emit call + result pair
                self._emit_call_result_pair(tool_call_id)
            else:
                # Call not yet registered - buffer the result
                self._pending_results[tool_call_id] = brief
        else:
            # No ID, emit immediately (fallback behavior)
            self._emit_result(brief, prefix)

    def _emit_result(self, brief: str, prefix: str | None) -> None:
        """Emit a result line to stderr."""
        if prefix:
            sys.stderr.write(f"[{prefix}]   └ ✓ {brief}\n")
        else:
            sys.stderr.write(f"  └ ✓ {brief}\n")
        sys.stderr.flush()

    def _emit_call_result_pair(self, tool_call_id: str) -> None:
        """Emit a tool call and its result as a pair."""
        call_info = self._pending_calls.get(tool_call_id)
        if not call_info or call_info["emitted"]:
            return

        # Emit the call
        sys.stderr.write(f"{call_info['display_str']}\n")
        call_info["emitted"] = True

        # Emit the result if available
        if tool_call_id in self._pending_results:
            brief = self._pending_results.pop(tool_call_id)
            self._emit_result(brief, call_info["prefix"])
        sys.stderr.flush()

    def _flush_pending_outputs(self) -> None:
        """Flush all pending tool calls and results in order."""
        for tc_id in list(self._call_order):
            call_info = self._pending_calls.get(tc_id)
            if call_info and not call_info["emitted"]:
                self._emit_call_result_pair(tc_id)
        # Clear tracking (keep pending_results for late arrivals)
        self._call_order.clear()


def _output_final_report(report_text: str, workspace_path: str) -> None:
    """Output final report with dynamic routing based on size.

    Small reports (< REPORT_STDOUT_THRESHOLD chars) are written to stdout directly.
    Large reports are saved to a file with user notification and preview.

    Args:
        report_text: The full report text to output.
        workspace_path: Workspace path for saving report files.
    """
    if len(report_text) < REPORT_STDOUT_THRESHOLD:
        # Small report: output to stdout
        sys.stdout.write("\n\n")
        sys.stdout.write(report_text)
        sys.stdout.write("\n")
    else:
        # Large report: write to file and show preview
        try:
            # Create reports directory in workspace
            reports_dir = Path(workspace_path) / ".soothe" / "reports"
            reports_dir.mkdir(parents=True, exist_ok=True)

            # Generate unique filename with timestamp
            import time

            timestamp = time.strftime("%Y%m%d_%H%M%S")
            report_path = reports_dir / f"report_{timestamp}.md"
            report_path.write_text(report_text, encoding="utf-8")

            # Show notification and preview
            sys.stdout.write(f"\n\n[Report saved to: {report_path}]\n")
            # Show preview (first ~500 chars)
            preview_len = 500
            if len(report_text) > preview_len:
                preview = report_text[:preview_len] + "\n...\n(truncated, see full report in file)"
            else:
                preview = report_text
            sys.stdout.write(f"\nPreview:\n{preview}\n")
        except Exception as e:
            # Fallback: write to temp file
            logger.warning("Failed to write report to workspace: %s", e)
            with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False) as f:
                f.write(report_text)
                sys.stdout.write(f"\n\n[Report saved to: {f.name}]\n")
    sys.stdout.flush()


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
    from soothe.utils import expand_path, set_workspace_root
    from soothe.ux.cli.progress import render_progress_event
    from soothe.ux.core.progress_verbosity import classify_custom_event, should_show
    from soothe.ux.core.rendering import resolve_namespace_label

    # Set workspace root for path display conversion
    workspace_path = str(expand_path(cfg.workspace_dir))
    set_workspace_root(workspace_path)

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

    verbosity = cfg.logging.verbosity

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

                # Handle internal context tracking for research events (IG-064)
                from soothe.subagents.research.events import TOOL_RESEARCH_INTERNAL_LLM

                if etype == TOOL_RESEARCH_INTERNAL_LLM:
                    state.internal_context_active = True
                    # Don't display internal events
                    continue

                # Exit internal context on non-internal research events
                if etype.startswith("soothe.tool.research.") and etype != TOOL_RESEARCH_INTERNAL_LLM:
                    state.internal_context_active = False

                if etype == FINAL_REPORT:
                    report_text = data.get("summary", "")
                    if report_text:
                        _output_final_report(report_text, workspace_path)
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
                        render_progress_event(etype, data, prefix=prefix)
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
