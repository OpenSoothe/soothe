"""HTTP client helpers for daemon cron REST endpoints (RFC-229)."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any

from soothe_sdk.client import http_rest_url_from_config


def parse_cron_slash_prompt(prompt: str) -> str | None:
    """Return natural-language cron text if ``prompt`` is a ``/cron`` slash command.

    Args:
        prompt: User input (e.g. ``/cron in 1 hour remind me to deploy``).

    Returns:
        Text after ``/cron``, or ``None`` if not a cron slash command.
    """
    stripped = prompt.strip()
    if not stripped.lower().startswith("/cron"):
        return None
    rest = stripped[len("/cron") :].strip()
    return rest


class CronHttpClient:
    """Synchronous HTTP client for ``/api/v1/cron/*`` endpoints."""

    def __init__(self, base_url: str, *, timeout: float = 60.0) -> None:
        self._base = base_url.rstrip("/")
        self._timeout = timeout

    def _request(
        self,
        method: str,
        path: str,
        *,
        body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        url = f"{self._base}{path}"
        data = None
        headers = {"Accept": "application/json"}
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                raw = resp.read().decode("utf-8")
                return json.loads(raw) if raw else {}
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            msg = f"HTTP {exc.code} for {path}: {detail}"
            raise RuntimeError(msg) from exc
        except urllib.error.URLError as exc:
            msg = f"Cannot reach daemon at {self._base}: {exc.reason}"
            raise RuntimeError(msg) from exc

    def add(self, text: str, *, priority: int | None = None) -> dict[str, Any]:
        """Submit a natural-language scheduled job."""
        body: dict[str, Any] = {"text": text}
        if priority is not None:
            body["priority"] = priority
        return self._request("POST", "/api/v1/cron/jobs", body=body)

    def list_jobs(self, *, status: str | None = None) -> dict[str, Any]:
        """List scheduled jobs."""
        path = "/api/v1/cron/jobs"
        if status:
            path = f"{path}?status={status}"
        return self._request("GET", path)

    def show(self, job_id: str) -> dict[str, Any]:
        """Fetch one job by id."""
        return self._request("GET", f"/api/v1/cron/jobs/{job_id}")

    def cancel(self, job_id: str) -> dict[str, Any]:
        """Cancel a pending job."""
        return self._request("DELETE", f"/api/v1/cron/jobs/{job_id}")


def cron_client_from_config(cfg: Any) -> CronHttpClient:
    """Build a cron HTTP client from CLI or soothe config."""
    return CronHttpClient(http_rest_url_from_config(cfg))


__all__ = [
    "CronHttpClient",
    "cron_client_from_config",
    "parse_cron_slash_prompt",
]
