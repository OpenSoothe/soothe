"""HTTP client for daemon autopilot REST endpoints (RFC-204 / RFC-222)."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any

from soothe_sdk.client.helpers import websocket_url_from_config

_HTTP_REST_DISABLED_HINT = (
    "HTTP REST is disabled on the daemon. Autopilot CLI commands require "
    "transports.http_rest.enabled: true in daemon_config.yml — then restart "
    "with 'soothed restart'."
)


def http_rest_url_from_config(cfg: Any) -> str:
    """Derive HTTP REST base URL from a config object's WebSocket settings.

    Args:
        cfg: CLI, daemon, or soothe config exposing websocket host/port.

    Returns:
        Base URL such as ``http://127.0.0.1:8765``.
    """
    ws_url = websocket_url_from_config(cfg)
    if ws_url.startswith("wss://"):
        return "https://" + ws_url[len("wss://") :]
    if ws_url.startswith("ws://"):
        return "http://" + ws_url[len("ws://") :]
    return ws_url


def ensure_http_rest_available(base_url: str, *, timeout: float = 5.0) -> None:
    """Verify the daemon exposes HTTP REST before autopilot commands run.

    Args:
        base_url: HTTP base URL (e.g. ``http://127.0.0.1:8765``).
        timeout: Request timeout in seconds.

    Raises:
        RuntimeError: When REST is unreachable or disabled (404 on /api/v1/health).
    """
    url = f"{base_url.rstrip('/')}/api/v1/health"
    req = urllib.request.Request(url, headers={"Accept": "application/json"}, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if resp.status != 200:  # noqa: PLR2004
                msg = f"HTTP REST health check failed with status {resp.status}"
                raise RuntimeError(msg)
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            raise RuntimeError(_HTTP_REST_DISABLED_HINT) from exc
        detail = exc.read().decode("utf-8", errors="replace")
        msg = f"HTTP REST health check failed ({exc.code}): {detail}"
        raise RuntimeError(msg) from exc
    except urllib.error.URLError as exc:
        msg = f"Cannot reach daemon HTTP REST at {base_url}: {exc.reason}"
        raise RuntimeError(msg) from exc


class AutopilotHttpClient:
    """Synchronous HTTP client for ``/api/v1/autopilot/*`` endpoints."""

    def __init__(self, base_url: str, *, timeout: float = 30.0) -> None:
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
            if exc.code == 404 and path.startswith("/api/v1/autopilot"):
                msg = _HTTP_REST_DISABLED_HINT
                raise RuntimeError(msg) from exc
            msg = f"HTTP {exc.code} for {path}: {detail}"
            raise RuntimeError(msg) from exc

    def submit(self, description: str, *, priority: int = 50) -> dict[str, Any]:
        """Submit a new autopilot task."""
        return self._request(
            "POST",
            "/api/v1/autopilot/submit",
            body={"description": description, "priority": priority},
        )

    def list_goals(self) -> dict[str, Any]:
        """List goals in the live autopilot DAG."""
        return self._request("GET", "/api/v1/autopilot/goals")

    def get_goal(self, goal_id: str) -> dict[str, Any]:
        """Fetch one goal by id."""
        return self._request("GET", f"/api/v1/autopilot/goals/{goal_id}")

    def cancel_goal(self, goal_id: str) -> dict[str, Any]:
        """Cancel a goal."""
        return self._request("DELETE", f"/api/v1/autopilot/goals/{goal_id}")

    def wake(self) -> dict[str, Any]:
        """Exit dreaming mode."""
        return self._request("POST", "/api/v1/autopilot/wake")

    def dream(self) -> dict[str, Any]:
        """Force dreaming mode."""
        return self._request("POST", "/api/v1/autopilot/dream")

    def approve(self, confirmation_id: str) -> dict[str, Any]:
        """Approve a MUST-confirmation."""
        return self._request("POST", f"/api/v1/autopilot/goals/{confirmation_id}/approve")

    def reject(self, confirmation_id: str) -> dict[str, Any]:
        """Reject a MUST-confirmation."""
        return self._request("POST", f"/api/v1/autopilot/goals/{confirmation_id}/reject")

    def status(self) -> dict[str, Any]:
        """Fetch autopilot status summary."""
        return self._request("GET", "/api/v1/autopilot/status")
