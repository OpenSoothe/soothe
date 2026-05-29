"""Tests for soothe_sdk AutopilotHttpClient URL helper."""

from __future__ import annotations

import urllib.error
from unittest.mock import MagicMock, patch

import pytest

from soothe_sdk.client.autopilot_http import (
    ensure_http_rest_available,
    http_rest_url_from_config,
)


class _Cfg:
    daemon_host = "127.0.0.1"
    daemon_port = 9001


def test_http_rest_url_from_cli_config() -> None:
    assert http_rest_url_from_config(_Cfg()) == "http://127.0.0.1:9001"


def test_ensure_http_rest_available_ok() -> None:
    mock_resp = MagicMock()
    mock_resp.status = 200
    mock_resp.__enter__ = MagicMock(return_value=mock_resp)
    mock_resp.__exit__ = MagicMock(return_value=False)
    with patch("urllib.request.urlopen", return_value=mock_resp):
        ensure_http_rest_available("http://127.0.0.1:8765")


def test_ensure_http_rest_available_404() -> None:
    err = urllib.error.HTTPError(
        "http://127.0.0.1:8765/api/v1/health",
        404,
        "Not Found",
        hdrs=None,
        fp=None,
    )
    with patch("urllib.request.urlopen", side_effect=err):
        with pytest.raises(RuntimeError, match="HTTP REST is disabled"):
            ensure_http_rest_available("http://127.0.0.1:8765")

