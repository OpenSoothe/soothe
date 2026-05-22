"""Tests for graceful connection-refused handling in Executor."""

import errno
from unittest.mock import MagicMock

from soothe.core.loop.engine.executor import Executor
from soothe.utils.network_errors import (
    format_connection_refusal_message,
    is_expected_connection_refusal,
)


class TestConnectionRefusalHelpers:
    def test_is_expected_connection_refusal_direct(self):
        err = ConnectionRefusedError(61, "Connect call failed")
        assert is_expected_connection_refusal(err) is True

    def test_is_expected_connection_refusal_oserror_errno(self):
        err = OSError(errno.ECONNREFUSED, "refused")
        assert is_expected_connection_refusal(err) is True

    def test_is_expected_connection_refusal_wrapped(self):
        inner = ConnectionRefusedError(
            61,
            "Multiple exceptions: [Errno 61] Connect call failed ('::1', 8080, 0, 0), "
            "[Errno 61] Connect call failed ('127.0.0.1', 8080)",
        )
        outer = RuntimeError("stream failed")
        outer.__cause__ = inner
        assert is_expected_connection_refusal(outer) is True

    def test_is_expected_connection_refusal_negative(self):
        assert is_expected_connection_refusal(ValueError("bad")) is False

    def test_format_connection_refusal_message_extracts_host_port(self):
        err = ConnectionRefusedError(
            61,
            "Multiple exceptions: [Errno 61] Connect call failed ('127.0.0.1', 8080)",
        )
        msg = format_connection_refusal_message(err)
        assert "127.0.0.1:8080" in msg
        assert "nothing is listening" in msg

    def test_format_connection_refusal_message_fallback(self):
        err = ConnectionRefusedError(61, "refused")
        msg = format_connection_refusal_message(err)
        assert "not accepting connections" in msg


def test_extract_error_message_connection_refusal_chain():
    inner = ConnectionRefusedError(
        61,
        "Multiple exceptions: [Errno 61] Connect call failed ('::1', 9380, 0, 0)",
    )
    outer = Exception("aiohttp failed")
    outer.__cause__ = inner
    executor = Executor(MagicMock())
    text = executor._extract_error_message(outer, "fallback")
    assert "::1:9380" in text or "not accepting connections" in text
