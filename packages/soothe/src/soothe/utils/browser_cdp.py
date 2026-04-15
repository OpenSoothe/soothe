"""Chrome DevTools Protocol (CDP) discovery utilities.

Provides functions to discover and connect to existing Chrome instances
with remote debugging enabled, and to clean up stale soothe-owned
Chrome processes that would block new launches via SingletonLock.
"""

from __future__ import annotations

import logging
import os
import re
import signal
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)

DEFAULT_CDP_PORTS = [9222, 9242, 9223, 9333]
"""Well-known ports to try before falling back to process discovery."""


async def discover_cdp_url(port: int = 9222) -> str | None:
    """Try to discover CDP URL from Chrome debugging endpoint.

    Args:
        port: Port number for Chrome debugging endpoint.

    Returns:
        WebSocket debugger URL if found, None otherwise.
    """
    try:
        import aiohttp

        async with (
            aiohttp.ClientSession() as session,
            session.get(
                f"http://localhost:{port}/json/version",
                timeout=aiohttp.ClientTimeout(total=2),
            ) as resp,
        ):
            if resp.status == 200:  # noqa: PLR2004
                data = await resp.json()
                cdp_url = data.get("webSocketDebuggerUrl")
                if cdp_url:
                    logger.info("Found Chrome CDP endpoint at port %d: %s", port, cdp_url)
                    return cdp_url
    except Exception as e:
        logger.debug("Failed to discover CDP at port %d: %s", port, e)
    return None


def _list_chrome_processes() -> list[dict[str, str]]:
    """List Chrome processes with their PID, args, and extracted metadata.

    Returns:
        List of dicts with keys: pid, args, user_data_dir, debug_port.
    """
    processes: list[dict[str, str]] = []
    try:
        result = subprocess.run(
            ["/bin/ps", "ax", "-o", "pid=,args="],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except Exception:
        logger.debug("Failed to list Chrome processes", exc_info=True)
        return processes

    for raw_line in result.stdout.splitlines():
        stripped = raw_line.strip()
        if not stripped or "--remote-debugging-port=" not in stripped:
            continue
        parts = stripped.split(None, 1)
        if len(parts) < 2:  # noqa: PLR2004
            continue
        pid_str, args = parts
        udd_match = re.search(r"--user-data-dir=(\S+)", args)
        port_match = re.search(r"--remote-debugging-port=(\d+)", args)
        processes.append(
            {
                "pid": pid_str.strip(),
                "args": args,
                "user_data_dir": udd_match.group(1) if udd_match else "",
                "debug_port": port_match.group(1) if port_match else "",
            }
        )
    return processes


def _discover_ports_from_processes() -> list[int]:
    """Extract ``--remote-debugging-port=PORT`` from running Chrome processes.

    Returns a deduplicated list of integer ports found (may be empty).
    """
    ports: set[int] = set()
    for proc in _list_chrome_processes():
        port_str = proc.get("debug_port", "")
        if port_str:
            port = int(port_str)
            if port > 0:
                ports.add(port)
    if ports:
        logger.debug("Discovered Chrome debugging ports from processes: %s", sorted(ports))
    return sorted(ports)


def find_soothe_chrome_processes(user_data_dir: str) -> list[dict[str, str]]:
    """Find Chrome processes launched with a specific user-data-dir.

    Args:
        user_data_dir: The soothe browser profile directory to match.

    Returns:
        List of process info dicts for matching Chrome processes.
    """
    canonical = os.path.realpath(user_data_dir)
    matches = []
    for proc in _list_chrome_processes():
        proc_udd = proc.get("user_data_dir", "")
        if proc_udd and os.path.realpath(proc_udd) == canonical:
            matches.append(proc)
    return matches


def cleanup_stale_chrome(user_data_dir: str) -> int:
    """Kill stale Chrome processes that are using a specific user-data-dir.

    This prevents SingletonLock conflicts when launching a new browser session.
    Only kills processes whose ``--user-data-dir`` matches the given path.

    Args:
        user_data_dir: The soothe browser profile directory.

    Returns:
        Number of processes killed.
    """
    stale = find_soothe_chrome_processes(user_data_dir)
    killed = 0
    for proc in stale:
        pid = int(proc["pid"])
        try:
            os.kill(pid, signal.SIGTERM)
            killed += 1
            logger.info(
                "Killed stale Chrome process PID %d (port %s, user-data-dir=%s)",
                pid,
                proc.get("debug_port", "?"),
                proc.get("user_data_dir", "?"),
            )
        except ProcessLookupError:
            logger.debug("Chrome PID %d already gone", pid)
        except PermissionError:
            logger.warning("No permission to kill Chrome PID %d", pid)
    if killed:
        _remove_stale_singleton_lock(user_data_dir)
    return killed


def _remove_stale_singleton_lock(user_data_dir: str) -> None:
    """Remove the SingletonLock symlink if present."""
    lock_path = Path(user_data_dir) / "SingletonLock"
    try:
        if lock_path.is_symlink() or lock_path.exists():
            lock_path.unlink()
            logger.debug("Removed stale SingletonLock at %s", lock_path)
    except OSError as e:
        logger.debug("Could not remove SingletonLock at %s: %s", lock_path, e)


async def find_soothe_cdp(user_data_dir: str) -> str | None:
    """Find a CDP endpoint from a soothe-owned Chrome process.

    Looks for Chrome processes using the given user-data-dir and returns
    the CDP URL if the process is still responsive.

    Args:
        user_data_dir: The soothe browser profile directory.

    Returns:
        CDP URL (``http://...``) if a live endpoint is found, None otherwise.
    """
    for proc in find_soothe_chrome_processes(user_data_dir):
        port_str = proc.get("debug_port", "")
        if not port_str:
            continue
        port = int(port_str)
        cdp_url = await discover_cdp_url(port)
        if cdp_url:
            logger.info("Found existing soothe Chrome CDP at port %d", port)
            return f"http://127.0.0.1:{port}/"
    return None


async def find_available_cdp() -> str | None:
    """Find an available Chrome CDP endpoint.

    Strategy:
      1. Try well-known ports first (fast, no subprocess).
      2. Fall back to extracting the actual port from running Chrome processes.

    Returns:
        WebSocket debugger URL if found, None otherwise.
    """
    for port in DEFAULT_CDP_PORTS:
        cdp_url = await discover_cdp_url(port)
        if cdp_url:
            return cdp_url

    for port in _discover_ports_from_processes():
        if port in DEFAULT_CDP_PORTS:
            continue
        cdp_url = await discover_cdp_url(port)
        if cdp_url:
            return cdp_url

    logger.info("No Chrome CDP endpoint found")
    return None
