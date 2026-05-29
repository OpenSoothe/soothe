"""Tests for soothe_sdk AutopilotHttpClient URL helper."""

from __future__ import annotations

from soothe_sdk.client.autopilot_http import http_rest_url_from_config


class _Cfg:
    daemon_host = "127.0.0.1"
    daemon_port = 9001


def test_http_rest_url_from_cli_config() -> None:
    assert http_rest_url_from_config(_Cfg()) == "http://127.0.0.1:9001"
