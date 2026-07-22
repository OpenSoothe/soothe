"""Tests for graceful connection-refused handling in Executor."""

import errno
import ssl
from unittest.mock import MagicMock

import pytest

from soothe.sloop.engine.executor import Executor
from soothe.sloop.utils.network_errors import (
    format_connection_refusal_message,
    format_ssl_certificate_message,
    format_tool_network_error,
    is_expected_connection_refusal,
    is_recoverable_tool_network_error,
    is_ssl_certificate_error,
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


class TestSslCertificateErrors:
    def test_ssl_cert_verification_error(self):
        err = ssl.SSLCertVerificationError(1, "[SSL: CERTIFICATE_VERIFY_FAILED] verify failed")
        assert is_ssl_certificate_error(err) is True

    def test_aiohttp_style_message(self):
        try:
            import aiohttp

            err = aiohttp.client_exceptions.ClientConnectorCertificateError(
                connection_key=None,  # type: ignore[arg-type]
                certificate_error=ssl.SSLCertVerificationError(1, "verify failed"),
            )
        except ImportError:
            pytest.skip("aiohttp not installed")
        else:
            assert is_ssl_certificate_error(err) is True

    def test_wrapped_ssl_in_chain(self):
        inner = ssl.SSLCertVerificationError(1, "certificate verify failed")
        outer = Exception("Cannot connect to host mcap.dev:443 ssl:True")
        outer.__cause__ = inner
        assert is_ssl_certificate_error(outer) is True
        msg = format_ssl_certificate_message(outer)
        assert "mcap.dev" in msg
        assert "verify_ssl" in msg

    def test_ssl_negative(self):
        assert is_ssl_certificate_error(ValueError("other")) is False


class TestRecoverableToolNetworkErrors:
    def test_connection_refusal_is_recoverable(self):
        assert is_recoverable_tool_network_error(ConnectionRefusedError(61, "x")) is True

    def test_ssl_is_recoverable(self):
        err = ssl.SSLCertVerificationError(1, "CERTIFICATE_VERIFY_FAILED")
        assert is_recoverable_tool_network_error(err) is True

    def test_format_tool_network_error_prefers_ssl(self):
        err = ssl.SSLCertVerificationError(1, "CERTIFICATE_VERIFY_FAILED")
        assert "verify_ssl" in format_tool_network_error(err)


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
