"""Output capture utilities for third-party library output redirection.

This module provides context managers to capture stdout/stderr output from
third-party libraries and convert them to structured progress events instead
of polluting the console with unstructured messages.
"""

from __future__ import annotations

import contextlib
import io
import logging
import sys
import types
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Iterator
    from typing import Self

logger = logging.getLogger(__name__)


class OutputCapture:
    """Context manager to capture and redirect stdout/stderr output.

    Captures output written to stdout/stderr during execution and converts
    it to progress events or log messages instead of printing directly.

    Args:
        source: Name of the component generating output (e.g., "wizsearch", "browser").
        suppress: Whether to suppress captured output (don't log or emit events).
        log_level: Log level for captured output (default: DEBUG).
        emit_progress: Whether to emit progress events for captured output.
        passthrough: Whether to also print output to original stream.
    """

    def __init__(
        self,
        source: str,
        *,
        suppress: bool = False,
        log_level: int = logging.DEBUG,
        emit_progress: bool = True,
        passthrough: bool = False,
    ) -> None:
        """Initialize output capture context manager."""
        self.source = source
        self.suppress = suppress
        self.log_level = log_level
        self.emit_progress = emit_progress
        self.passthrough = passthrough
        self._stdout_buffer = io.StringIO()
        self._stderr_buffer = io.StringIO()
        self._original_stdout: Any = None
        self._original_stderr: Any = None

    def __enter__(self) -> Self:
        """Enter the context and redirect stdout/stderr."""
        self._original_stdout = sys.stdout
        self._original_stderr = sys.stderr

        # Create wrapper that optionally passes through
        if self.passthrough:
            sys.stdout = _PassthroughStream(self._stdout_buffer, self._original_stdout)
            sys.stderr = _PassthroughStream(self._stderr_buffer, self._original_stderr)
        else:
            sys.stdout = self._stdout_buffer
            sys.stderr = self._stderr_buffer

        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: types.TracebackType | None,
    ) -> None:
        """Exit the context and restore stdout/stderr."""
        # Restore original streams
        sys.stdout = self._original_stdout
        sys.stderr = self._original_stderr

        # Process captured output
        stdout_content = self._stdout_buffer.getvalue()
        stderr_content = self._stderr_buffer.getvalue()

        if not self.suppress:
            self._process_output(stdout_content, stderr_content)

    def _process_output(self, stdout: str, stderr: str) -> None:
        """Process captured output and emit as log/progress events."""
        # Process stdout
        if stdout.strip():
            for line in stdout.strip().split("\n"):
                if line.strip():
                    self._emit_line(line, is_stderr=False)

        # Process stderr
        if stderr.strip():
            for line in stderr.strip().split("\n"):
                if line.strip():
                    self._emit_line(line, is_stderr=True)

    def _emit_line(self, line: str, *, is_stderr: bool = False) -> None:
        """Emit a single line as log message and/or progress event."""
        # Always log at configured level using the module logger
        logger.log(self.log_level, "[%s] %s", self.source, line)

        # Optionally emit as progress event
        if self.emit_progress:
            try:
                from soothe.utils.progress import emit_progress

                # Get the caller's logger (not our module logger)
                caller_logger = logging.getLogger(self.source)
                emit_progress(
                    {
                        "type": f"soothe.output.{self.source}",
                        "message": line,
                        "is_stderr": is_stderr,
                    },
                    caller_logger,
                )
            except Exception:
                # Don't fail if progress emission fails
                logger.debug("Failed to emit progress event for output", exc_info=True)


class _PassthroughStream(io.StringIO):
    """Stream that writes to both buffer and original stream."""

    def __init__(self, buffer: io.StringIO, original: Any) -> None:
        """Initialize passthrough stream."""
        super().__init__()
        self._buffer = buffer
        self._original = original

    def write(self, s: str) -> int:
        """Write to both buffer and original stream."""
        self._buffer.write(s)
        if self._original:
            return self._original.write(s)
        return len(s)

    def flush(self) -> None:
        """Flush both streams."""
        self._buffer.flush()
        if self._original:
            self._original.flush()


@contextlib.contextmanager
def capture_subagent_output(
    source: str,
    *,
    suppress: bool = False,
    log_level: int = logging.DEBUG,
    emit_progress: bool = False,
    passthrough: bool = False,
) -> Iterator[OutputCapture]:
    """Context manager to capture third-party library output.

    This is a convenience wrapper around OutputCapture for common use cases.

    Args:
        source: Name of the component generating output.
        suppress: Whether to suppress captured output completely.
        log_level: Log level for captured output.
        emit_progress: Whether to emit progress events for each line.
        passthrough: Whether to also print to original stream.

    Yields:
        OutputCapture instance for accessing captured content.

    Example:
        with capture_subagent_output("browser") as capture:
            # Third-party library output is captured
            result = some_library_function()
        # Output is logged and optionally emitted as progress events
    """
    capture = OutputCapture(
        source,
        suppress=suppress,
        log_level=log_level,
        emit_progress=emit_progress,
        passthrough=passthrough,
    )
    with capture:
        yield capture
