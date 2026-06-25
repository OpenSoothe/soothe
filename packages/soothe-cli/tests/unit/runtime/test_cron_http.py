"""Tests for cron HTTP helpers."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from soothe_cli.runtime.cron_http import CronHttpClient, parse_cron_slash_prompt


def test_parse_cron_slash_prompt() -> None:
    assert parse_cron_slash_prompt("/cron in 1 hour check deploy") == "in 1 hour check deploy"
    assert (
        parse_cron_slash_prompt("  /CRON  tomorrow at 9am standup  ") == "tomorrow at 9am standup"
    )
    assert parse_cron_slash_prompt("hello world") is None
    assert parse_cron_slash_prompt("/cron") == ""


def test_cron_http_client_add() -> None:
    payload = {"job": {"id": "job1", "description": "task"}}
    mock_resp = MagicMock()
    mock_resp.read.return_value = json.dumps(payload).encode()
    mock_resp.__enter__ = MagicMock(return_value=mock_resp)
    mock_resp.__exit__ = MagicMock(return_value=False)

    with patch("urllib.request.urlopen", return_value=mock_resp) as urlopen:
        client = CronHttpClient("http://127.0.0.1:8765")
        result = client.add("in 1 hour task", priority=55)

    assert result == payload
    req = urlopen.call_args[0][0]
    assert req.full_url == "http://127.0.0.1:8765/api/v1/cron/jobs"
    assert req.method == "POST"
    body = json.loads(req.data.decode())
    assert body == {"text": "in 1 hour task", "priority": 55}


def test_cron_http_client_list_and_cancel() -> None:
    mock_resp = MagicMock()
    mock_resp.read.return_value = b'{"jobs":[]}'
    mock_resp.__enter__ = MagicMock(return_value=mock_resp)
    mock_resp.__exit__ = MagicMock(return_value=False)

    with patch("urllib.request.urlopen", return_value=mock_resp):
        client = CronHttpClient("http://127.0.0.1:8765")
        assert client.list_jobs(status="pending") == {"jobs": []}
        mock_resp.read.return_value = b'{"cancelled":true}'
        assert client.cancel("abc") == {"cancelled": True}


def test_cron_http_client_raises_on_http_error() -> None:
    import urllib.error

    err = urllib.error.HTTPError(
        url="http://127.0.0.1:8765/api/v1/cron/jobs",
        code=400,
        msg="Bad Request",
        hdrs=MagicMock(),
        fp=MagicMock(read=MagicMock(return_value=b'{"detail":"bad"}')),
    )
    with patch("urllib.request.urlopen", side_effect=err):
        client = CronHttpClient("http://127.0.0.1:8765")
        with pytest.raises(RuntimeError, match="HTTP 400"):
            client.add("bad input")
