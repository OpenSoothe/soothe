"""Shared helpers for outbound network failures (connection refused, TLS verify, etc.)."""

from __future__ import annotations

import errno
import re
import ssl
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass


def collect_related_exceptions(exc: BaseException) -> list[BaseException]:
    """Collect this exception plus chained ``__cause__`` / ``__context__`` (deduplicated)."""
    out: list[BaseException] = []
    seen: set[int] = set()

    def visit(e: BaseException | None) -> None:
        if e is None or id(e) in seen:
            return
        seen.add(id(e))
        out.append(e)
        visit(e.__cause__)
        ctx = getattr(e, "__context__", None)
        if ctx is not None and ctx is not e.__cause__:
            visit(ctx)

    visit(exc)
    return out


def is_expected_connection_refusal(exc: BaseException) -> bool:
    """True when failure is connection refused (local service down / wrong port)."""
    for e in collect_related_exceptions(exc):
        if isinstance(e, ConnectionRefusedError):
            return True
        if isinstance(e, OSError) and getattr(e, "errno", None) == errno.ECONNREFUSED:
            return True
    return False


def format_connection_refusal_message(exc: BaseException) -> str:
    """Short, actionable message for connection-refused chains (e.g. aiohttp → OSError)."""
    combined = " ".join(str(e) for e in collect_related_exceptions(exc))
    m = re.search(r"Connect call failed\s*\(\s*'([^']+)'\s*,\s*(\d+)", combined)
    if m:
        host, port = m.group(1), m.group(2)
        return (
            f"Connection refused to {host}:{port} — nothing is listening there. "
            "Start the service or correct the host/port."
        )
    return (
        "Connection refused — the target service is not accepting connections. "
        "Verify it is running and that the host and port are correct."
    )


def is_ssl_certificate_error(exc: BaseException) -> bool:
    """True when TLS certificate verification failed (proxy / self-signed chain)."""
    for e in collect_related_exceptions(exc):
        if isinstance(e, ssl.SSLCertVerificationError):
            return True
        type_name = type(e).__name__
        if type_name in ("ClientConnectorCertificateError", "CertificateError"):
            return True
        msg = str(e)
        if "CERTIFICATE_VERIFY_FAILED" in msg or "certificate verify failed" in msg.lower():
            return True
    return False


def format_ssl_certificate_message(exc: BaseException) -> str:
    """Actionable message for TLS verification failures."""
    combined = " ".join(str(e) for e in collect_related_exceptions(exc))
    m = re.search(r"Cannot connect to host ([^:\s]+):(\d+)", combined)
    if m:
        host, port = m.group(1), m.group(2)
        return (
            f"TLS certificate verification failed for {host}:{port}. "
            "The site may use a corporate proxy or self-signed certificate. "
            "Try another URL or set tools.http_requests.verify_ssl to false in config "
            "(less secure)."
        )
    return (
        "TLS certificate verification failed for the requested URL. "
        "Try another source or set tools.http_requests.verify_ssl to false in config "
        "(less secure)."
    )


def is_recoverable_tool_network_error(exc: BaseException) -> bool:
    """True when a tool HTTP failure should be returned to the model, not abort the step."""
    return is_expected_connection_refusal(exc) or is_ssl_certificate_error(exc)


def format_tool_network_error(exc: BaseException) -> str:
    """User-facing message for recoverable tool network errors."""
    if is_ssl_certificate_error(exc):
        return format_ssl_certificate_message(exc)
    if is_expected_connection_refusal(exc):
        return format_connection_refusal_message(exc)
    return str(exc)
