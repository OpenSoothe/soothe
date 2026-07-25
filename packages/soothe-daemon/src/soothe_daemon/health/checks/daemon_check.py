"""Daemon health check implementation."""

from __future__ import annotations

import os

from soothe_daemon.config import SootheDaemonConfig
from soothe_daemon.health.formatters import aggregate_status
from soothe_daemon.health.models import CategoryResult, CheckResult, CheckStatus


def _check_pid_file(*, websocket_ok: bool = False) -> CheckResult:
    """Check PID file validity."""
    from soothe_daemon.bootstrap.paths import pid_path

    pf = pid_path()
    if not pf.exists():
        if websocket_ok:
            return CheckResult(
                name="pid_file",
                status=CheckStatus.INFO,
                message=f"PID file not found at {pf} (daemon reachable via WebSocket)",
                details={"path": str(pf)},
            )
        return CheckResult(
            name="pid_file",
            status=CheckStatus.INFO,
            message=f"PID file not found at {pf} (daemon not running)",
            details={"path": str(pf)},
        )

    try:
        pid_str = pf.read_text().strip()
        pid = int(pid_str)
    except (ValueError, OSError) as e:
        return CheckResult(
            name="pid_file",
            status=CheckStatus.WARNING,
            message=f"Invalid PID file: {e}",
            details={"path": str(pf)},
        )

    return CheckResult(
        name="pid_file",
        status=CheckStatus.OK,
        message=f"PID file exists with PID {pid}",
        details={"pid": pid, "path": str(pf)},
    )


def _check_process_alive(pid: int) -> CheckResult:
    """Check if process is alive."""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return CheckResult(
            name="process_alive",
            status=CheckStatus.ERROR,
            message=f"Process {pid} not found (daemon crashed?)",
            details={"pid": pid},
        )
    except PermissionError:
        # Process exists but we don't have permission to signal it
        return CheckResult(
            name="process_alive",
            status=CheckStatus.OK,
            message=f"Process {pid} running (no signal permission)",
            details={"pid": pid},
        )
    except OSError as e:
        return CheckResult(
            name="process_alive",
            status=CheckStatus.ERROR,
            message=f"Error checking process: {e}",
            details={"pid": pid},
        )

    return CheckResult(
        name="process_alive",
        status=CheckStatus.OK,
        message=f"Process {pid} is running",
        details={"pid": pid},
    )


def _check_websocket_connectivity(config: SootheDaemonConfig | None) -> CheckResult:
    """Check WebSocket transport connectivity (RFC-450)."""
    from soothe_daemon.server import SootheDaemon

    ws_host = config.transports.websocket.host if config else "127.0.0.1"
    ws_port = config.transports.websocket.port if config else 8765

    # Use existing port check method from server.py
    if SootheDaemon._is_port_live(ws_host, ws_port):
        return CheckResult(
            name="websocket_connectivity",
            status=CheckStatus.OK,
            message=f"WebSocket accepting connections at {ws_host}:{ws_port}",
            details={"host": ws_host, "port": ws_port},
        )

    return CheckResult(
        name="websocket_connectivity",
        status=CheckStatus.INFO,
        message="WebSocket not accepting connections (daemon not running)",
        details={"host": ws_host, "port": ws_port},
    )


async def _check_daemon_readiness(config: SootheDaemonConfig | None) -> CheckResult:
    """Check daemon readiness state via WebSocket handshake (RFC-450).

    Drains the initial ``status`` push (and other non-ack frames) before
    requiring ``connection_ack``, matching admin RPC handshake behavior.
    """
    import asyncio
    import json

    import websockets
    from soothe_sdk.wire.codec import (
        ConnectionInitEnvelope,
        ConnectionInitParams,
        encode_envelope,
    )

    ws_host = config.transports.websocket.host if config else "127.0.0.1"
    ws_port = config.transports.websocket.port if config else 8765
    ws_url = f"ws://{ws_host}:{ws_port}"

    init = ConnectionInitEnvelope(
        params=ConnectionInitParams(
            client_version="health-check",
            client_name="soothed-doctor",
            accept_proto=["1"],
            capabilities=["streaming", "heartbeat"],
        )
    )

    try:
        async with websockets.connect(ws_url, open_timeout=2.0) as ws:
            await ws.send(encode_envelope(init))
            loop = asyncio.get_running_loop()
            deadline = loop.time() + 2.0
            while True:
                remaining = deadline - loop.time()
                if remaining <= 0:
                    return CheckResult(
                        name="daemon_readiness",
                        status=CheckStatus.WARNING,
                        message="Timed out waiting for connection_ack",
                        details={
                            "remediation": "Check daemon logs; confirm protocol-1 handshake",
                        },
                    )

                raw = await asyncio.wait_for(ws.recv(), timeout=remaining)
                if isinstance(raw, bytes):
                    raw = raw.decode()
                data = json.loads(raw)
                msg_type = data.get("type")

                # Daemon pushes ``status`` on connect before ack (RFC-450).
                if msg_type in ("status", "pong"):
                    continue
                if msg_type == "error":
                    return CheckResult(
                        name="daemon_readiness",
                        status=CheckStatus.WARNING,
                        message=f"Handshake error: {data.get('message', data)}",
                        details={"frame": data},
                    )
                if msg_type != "connection_ack":
                    continue

                ack_result = data.get("result") or {}
                state = ack_result.get("readiness_state", "unknown")
                status_map = {
                    "ready": CheckStatus.OK,
                    "degraded": CheckStatus.WARNING,
                    "error": CheckStatus.ERROR,
                    "starting": CheckStatus.INFO,
                    "warming": CheckStatus.INFO,
                    "stopped": CheckStatus.INFO,
                    "incompatible": CheckStatus.ERROR,
                }
                return CheckResult(
                    name="daemon_readiness",
                    status=status_map.get(state, CheckStatus.WARNING),
                    message=f"Daemon readiness state: {state}",
                    details={
                        "state": state,
                        "protocol_version": ack_result.get("protocol_version"),
                        "server_version": ack_result.get("server_version"),
                    },
                )
    except Exception as e:
        return CheckResult(
            name="daemon_readiness",
            status=CheckStatus.INFO,
            message=f"Readiness check failed: {e}",
            details={"impact": "Port may be open but not a soothed WebSocket"},
        )


def _check_daemon_uptime(pid: int) -> CheckResult:
    """Calculate daemon uptime from PID start time."""
    try:
        import time
        from datetime import UTC, datetime

        import psutil

        process = psutil.Process(pid)
        start_time = process.create_time()
        uptime_seconds = time.time() - start_time

        hours = int(uptime_seconds // 3600)
        minutes = int((uptime_seconds % 3600) // 60)

        return CheckResult(
            name="daemon_uptime",
            status=CheckStatus.INFO,
            message=f"Daemon uptime: {hours}h {minutes}m",
            details={
                "pid": pid,
                "start_time": datetime.fromtimestamp(start_time, UTC).isoformat(),
                "uptime_seconds": uptime_seconds,
            },
        )
    except Exception as e:
        return CheckResult(
            name="daemon_uptime",
            status=CheckStatus.WARNING,
            message=f"Uptime check failed: {e}",
        )


def _check_stale_locks(config: SootheDaemonConfig | None) -> CheckResult | None:
    """Check for stale PID files and zombie daemon.

    Returns ``None`` when there is nothing notable to report (keeps doctor quiet).
    """
    from soothe_daemon.bootstrap.paths import pid_path
    from soothe_daemon.server import SootheDaemon

    pf = pid_path()
    issues: list[str] = []

    if pf.exists():
        try:
            pid_str = pf.read_text().strip()
            pid = int(pid_str)
            os.kill(pid, 0)
        except (ValueError, ProcessLookupError, OSError):
            issues.append(f"Stale PID file at {pf}")

    if pf.exists():
        try:
            pid_str = pf.read_text().strip()
            pid = int(pid_str)
            os.kill(pid, 0)

            ws_host = config.transports.websocket.host if config else "127.0.0.1"
            ws_port = config.transports.websocket.port if config else 8765
            if not SootheDaemon._is_port_live(ws_host, ws_port):
                issues.append(f"Zombie daemon (PID {pid} alive but WebSocket port {ws_port} dead)")
        except (ValueError, ProcessLookupError, OSError):
            pass

    if not issues:
        return None

    return CheckResult(
        name="stale_locks",
        status=CheckStatus.WARNING,
        message="Stale files detected: " + "; ".join(issues),
        details={"issues": issues},
    )


def _category_status(checks: list[CheckResult]) -> CheckStatus:
    """Aggregate status ignoring informational noise (INFO/SKIPPED)."""
    substantive = [
        c.status for c in checks if c.status not in (CheckStatus.INFO, CheckStatus.SKIPPED)
    ]
    if substantive:
        return aggregate_status(substantive)
    return aggregate_status([c.status for c in checks])


def _category_message(status: CheckStatus, *, websocket_ok: bool) -> str:
    if websocket_ok and status == CheckStatus.OK:
        return "Daemon healthy (WebSocket responsive)"
    if websocket_ok and status == CheckStatus.WARNING:
        return "Daemon reachable but not fully ready"
    if websocket_ok and status == CheckStatus.ERROR:
        return "Daemon reachable but unhealthy"
    if status == CheckStatus.ERROR:
        return "Daemon unhealthy"
    if status == CheckStatus.WARNING:
        return "Daemon not running cleanly"
    return "Daemon not running (optional for CLI usage)"


async def check_daemon(config: SootheDaemonConfig | None = None) -> CategoryResult:
    """Check daemon health with WebSocket-first priority (RFC-450).

    Uses WebSocket-first logic to prioritize actual daemon responsiveness
    over PID file checks.

    Args:
        config: ``SootheDaemonConfig`` instance for transport configuration

    Returns:
        CategoryResult with daemon check results
    """
    checks: list[CheckResult] = []

    ws_result = _check_websocket_connectivity(config)
    checks.append(ws_result)

    if ws_result.status == CheckStatus.OK:
        checks.append(await _check_daemon_readiness(config))

        pid_result = _check_pid_file(websocket_ok=True)
        checks.append(pid_result)

        pid = pid_result.details.get("pid")
        if isinstance(pid, int):
            checks.append(_check_process_alive(pid))
            checks.append(_check_daemon_uptime(pid))

        stale = _check_stale_locks(config)
        if stale is not None:
            checks.append(stale)

        overall_status = _category_status(checks)
        return CategoryResult(
            category="daemon",
            status=overall_status,
            checks=checks,
            message=_category_message(overall_status, websocket_ok=True),
        )

    # WebSocket failed - fallback to PID checks
    pid_result = _check_pid_file(websocket_ok=False)
    checks.append(pid_result)

    if pid_result.status == CheckStatus.OK and pid_result.details.get("pid"):
        pid = pid_result.details["pid"]
        process_result = _check_process_alive(pid)
        checks.append(process_result)

        if process_result.status == CheckStatus.OK:
            stale = _check_stale_locks(config)
            if stale is not None:
                checks.append(stale)
            else:
                checks.append(
                    CheckResult(
                        name="stale_locks",
                        status=CheckStatus.WARNING,
                        message=(f"Zombie daemon (PID {pid} alive but WebSocket dead)"),
                    )
                )

            return CategoryResult(
                category="daemon",
                status=CheckStatus.ERROR,
                checks=checks,
                message="Zombie daemon (process alive but WebSocket dead)",
            )

        checks.append(
            CheckResult(
                name="stale_locks",
                status=CheckStatus.WARNING,
                message="Stale PID file (process not running)",
            )
        )

        return CategoryResult(
            category="daemon",
            status=CheckStatus.WARNING,
            checks=checks,
            message="Daemon not running (stale PID file)",
        )

    stale = _check_stale_locks(config)
    if stale is not None:
        checks.append(stale)

    overall_status = _category_status(checks)
    return CategoryResult(
        category="daemon",
        status=overall_status,
        checks=checks,
        message=_category_message(overall_status, websocket_ok=False),
    )
