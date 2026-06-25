"""Unit tests for daemon cron_add RPC handler (RFC-229)."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from soothe.foundation.cron import ExtractionError
from soothe.foundation.cron.models import (
    DEFAULT_CRON_USER_ID,
    CronJob,
    JobStatus,
    ScheduleKind,
)

from soothe_daemon.server.commands import _cmd_cron_add


def _sample_job() -> CronJob:
    return CronJob(
        id="job001",
        user_id=DEFAULT_CRON_USER_ID,
        description="Check deploy",
        schedule_kind=ScheduleKind.DELAY,
        schedule_value="1h",
        status=JobStatus.PENDING,
        next_run=datetime(2026, 6, 25, 12, 0, 0, tzinfo=UTC),
    )


@pytest.mark.asyncio
async def test_cmd_cron_add_success() -> None:
    """cron_add uses DEFAULT_CRON_USER_ID and returns job payload."""
    daemon = MagicMock()
    job = _sample_job()
    daemon._cron_service = MagicMock()
    daemon._cron_service.add_job = AsyncMock(return_value=job)

    result = await _cmd_cron_add(
        daemon,
        checkpoint_thread_id="thread-1",
        params={"text": "in 1 hour check deploy", "priority": 60},
        loop_id="loop-xyz",
    )

    daemon._cron_service.add_job.assert_awaited_once_with(
        "in 1 hour check deploy",
        DEFAULT_CRON_USER_ID,
        priority=60,
    )
    payload = result["cron_add"]
    assert payload["id"] == "job001"
    assert payload["description"] == "Check deploy"
    assert payload["status"] == "pending"


@pytest.mark.asyncio
async def test_cmd_cron_add_missing_text() -> None:
    daemon = MagicMock()
    with pytest.raises(ValueError, match="Natural language text required"):
        await _cmd_cron_add(daemon, None, {}, loop_id="loop-1")


@pytest.mark.asyncio
async def test_cmd_cron_add_extraction_error() -> None:
    daemon = MagicMock()
    daemon._cron_service = MagicMock()
    daemon._cron_service.add_job = AsyncMock(
        side_effect=ExtractionError("Low confidence", None),
    )
    with pytest.raises(ValueError, match="Low confidence"):
        await _cmd_cron_add(
            daemon,
            None,
            {"text": "unclear schedule"},
            loop_id="loop-1",
        )


@pytest.mark.asyncio
async def test_cmd_cron_add_lazy_service_creation(monkeypatch: pytest.MonkeyPatch) -> None:
    """When daemon has no cron service, handler creates one."""
    daemon = MagicMock()
    daemon._cron_service = None
    daemon._config = MagicMock()
    daemon._autopilot_service = MagicMock()
    job = _sample_job()

    mock_instance = MagicMock()
    mock_instance.add_job = AsyncMock(return_value=job)
    mock_cls = MagicMock(return_value=mock_instance)
    monkeypatch.setattr("soothe.foundation.cron.CronService", mock_cls)

    result = await _cmd_cron_add(
        daemon,
        None,
        {"text": "in 2 hours ping"},
        loop_id="loop-1",
    )

    mock_cls.assert_called_once_with(config=daemon._config, autopilot=daemon._autopilot_service)
    assert daemon._cron_service is mock_instance
    assert result["cron_add"]["id"] == "job001"
