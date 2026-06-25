"""Unit tests for cron HTTP REST routes (RFC-229)."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient
from soothe.foundation.cron import ExtractionError
from soothe.foundation.cron.models import (
    DEFAULT_CRON_USER_ID,
    CronJob,
    ScheduleKind,
)

from soothe_daemon.channels.http_rest import HttpRestChannel
from soothe_daemon.config.models import HttpRestConfig


def _sample_job(job_id: str = "abc123def456") -> CronJob:
    return CronJob(
        id=job_id,
        user_id=DEFAULT_CRON_USER_ID,
        description="Check deploy",
        schedule_kind=ScheduleKind.DELAY,
        schedule_value="1h",
        next_run=datetime(2026, 6, 25, 10, 0, 0, tzinfo=UTC),
    )


@pytest.fixture
def cron_http() -> tuple[TestClient, MagicMock]:
    """HTTP client and mocked CronService."""
    cron_service = MagicMock()
    cron_service.list_jobs = AsyncMock(return_value=[_sample_job()])
    cron_service.show_job = AsyncMock(return_value=_sample_job())
    cron_service.cancel_job = AsyncMock(return_value=True)
    cron_service.add_job = AsyncMock(return_value=_sample_job("newjob000001"))

    channel = HttpRestChannel(
        HttpRestConfig(enabled=True, host="127.0.0.1", port=8765),
        manager=MagicMock(),
        cron_service=cron_service,
    )
    return TestClient(channel._app), cron_service


class TestCronHttpRestRoutes:
    """CRUD coverage for /api/v1/cron/jobs."""

    def test_list_jobs(self, cron_http: tuple[TestClient, MagicMock]) -> None:
        client, service = cron_http
        response = client.get("/api/v1/cron/jobs")
        assert response.status_code == 200
        data = response.json()
        assert data["source"] == "cron_service"
        assert len(data["jobs"]) == 1
        assert data["jobs"][0]["id"] == "abc123def456"
        service.list_jobs.assert_awaited_once_with(DEFAULT_CRON_USER_ID, status=None)

    def test_list_jobs_status_filter(self, cron_http: tuple[TestClient, MagicMock]) -> None:
        client, service = cron_http
        response = client.get("/api/v1/cron/jobs?status=pending")
        assert response.status_code == 200
        service.list_jobs.assert_awaited_once_with(DEFAULT_CRON_USER_ID, status="pending")

    def test_create_job(self, cron_http: tuple[TestClient, MagicMock]) -> None:
        client, service = cron_http
        response = client.post(
            "/api/v1/cron/jobs",
            json={"text": "in 1 hour check deploy", "priority": 70},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["source"] == "cron_service"
        assert body["job"]["id"] == "newjob000001"
        service.add_job.assert_awaited_once_with(
            "in 1 hour check deploy",
            DEFAULT_CRON_USER_ID,
            priority=70,
        )

    def test_create_job_missing_text(self, cron_http: tuple[TestClient, MagicMock]) -> None:
        client, _service = cron_http
        response = client.post("/api/v1/cron/jobs", json={})
        assert response.status_code == 400
        assert "text is required" in response.json()["detail"]

    def test_create_job_extraction_error(self, cron_http: tuple[TestClient, MagicMock]) -> None:
        client, service = cron_http
        service.add_job = AsyncMock(
            side_effect=ExtractionError("Could not parse schedule", None),
        )
        response = client.post("/api/v1/cron/jobs", json={"text": "maybe someday"})
        assert response.status_code == 400
        assert "Could not parse schedule" in response.json()["detail"]

    def test_show_job(self, cron_http: tuple[TestClient, MagicMock]) -> None:
        client, service = cron_http
        response = client.get("/api/v1/cron/jobs/abc123def456")
        assert response.status_code == 200
        assert response.json()["job"]["description"] == "Check deploy"
        service.show_job.assert_awaited_once_with("abc123def456", DEFAULT_CRON_USER_ID)

    def test_show_job_not_found(self, cron_http: tuple[TestClient, MagicMock]) -> None:
        client, service = cron_http
        service.show_job = AsyncMock(return_value=None)
        response = client.get("/api/v1/cron/jobs/missing")
        assert response.status_code == 404

    def test_cancel_job(self, cron_http: tuple[TestClient, MagicMock]) -> None:
        client, service = cron_http
        response = client.delete("/api/v1/cron/jobs/abc123def456")
        assert response.status_code == 200
        assert response.json()["cancelled"] is True
        service.cancel_job.assert_awaited_once_with("abc123def456", DEFAULT_CRON_USER_ID)

    def test_cancel_job_not_found(self, cron_http: tuple[TestClient, MagicMock]) -> None:
        client, service = cron_http
        service.cancel_job = AsyncMock(return_value=False)
        response = client.delete("/api/v1/cron/jobs/abc123def456")
        assert response.status_code == 404

    def test_cron_service_unavailable(self) -> None:
        channel = HttpRestChannel(
            HttpRestConfig(enabled=True, host="127.0.0.1", port=8765),
            manager=MagicMock(),
            cron_service=None,
        )
        client = TestClient(channel._app)
        response = client.get("/api/v1/cron/jobs")
        assert response.status_code == 503
