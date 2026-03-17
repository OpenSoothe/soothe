"""Tests for output capture utility."""

from __future__ import annotations

import logging
import sys
from io import StringIO

from soothe.utils.output_capture import OutputCapture, capture_subagent_output


def test_output_capture_stdout():
    """Test that stdout is captured and logged."""
    # Setup a string buffer for log capture on the output_capture module logger
    log_buffer = StringIO()
    handler = logging.StreamHandler(log_buffer)
    handler.setLevel(logging.DEBUG)
    logger = logging.getLogger("soothe.utils.output_capture")
    logger.addHandler(handler)
    logger.setLevel(logging.DEBUG)

    original_stdout = sys.stdout
    with OutputCapture("test_source", log_level=logging.DEBUG, emit_progress=False):
        print("This is a test message")  # noqa: T201
        # Force flush
        sys.stdout.flush()

    # Restore stdout
    sys.stdout = original_stdout

    log_contents = log_buffer.getvalue()
    assert "This is a test message" in log_contents
    assert "[test_source]" in log_contents

    # Clean up
    logger.removeHandler(handler)


def test_output_capture_suppress():
    """Test that output can be completely suppressed."""
    log_buffer = StringIO()
    handler = logging.StreamHandler(log_buffer)
    handler.setLevel(logging.DEBUG)
    logger = logging.getLogger("soothe.utils.output_capture")
    logger.addHandler(handler)
    logger.setLevel(logging.DEBUG)

    original_stdout = sys.stdout
    with OutputCapture("test_source", suppress=True, log_level=logging.DEBUG):
        print("This should not be logged")  # noqa: T201

    sys.stdout = original_stdout

    log_contents = log_buffer.getvalue()
    assert "This should not be logged" not in log_contents

    # Clean up
    logger.removeHandler(handler)


def test_capture_subagent_output_context():
    """Test the convenience context manager."""
    log_buffer = StringIO()
    handler = logging.StreamHandler(log_buffer)
    handler.setLevel(logging.DEBUG)
    logger = logging.getLogger("soothe.utils.output_capture")
    logger.addHandler(handler)
    logger.setLevel(logging.DEBUG)

    original_stdout = sys.stdout
    with capture_subagent_output("wizsearch", suppress=True):
        print("Wizsearch output")  # noqa: T201

    sys.stdout = original_stdout

    # Output should be captured (not printed to stdout)
    # and not logged due to suppress=True
    log_contents = log_buffer.getvalue()
    assert "Wizsearch output" not in log_contents

    # Clean up
    logger.removeHandler(handler)


def test_output_capture_stderr():
    """Test that stderr is captured."""
    log_buffer = StringIO()
    handler = logging.StreamHandler(log_buffer)
    handler.setLevel(logging.DEBUG)
    logger = logging.getLogger("soothe.utils.output_capture")
    logger.addHandler(handler)
    logger.setLevel(logging.DEBUG)

    original_stderr = sys.stderr
    with OutputCapture("test_source", log_level=logging.DEBUG, emit_progress=False):
        print("Error message", file=sys.stderr)  # noqa: T201
        sys.stderr.flush()

    sys.stderr = original_stderr

    log_contents = log_buffer.getvalue()
    assert "Error message" in log_contents

    # Clean up
    logger.removeHandler(handler)
