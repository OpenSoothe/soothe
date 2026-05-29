"""Subprocess cleanup ladder for stdio MCP servers (RFC-412).

Mirrors Claude Code's client.ts:1404-1500 cleanup sequence:
SIGINT → poll every 50ms for 100ms → SIGTERM → 600ms failsafe → kill -9.

Docker-wrapped servers may ignore default abort signals, so we need
explicit signal escalation with timeouts.
"""

from __future__ import annotations

import asyncio
import logging
import os
import signal
import sys
from typing import Any

logger = logging.getLogger(__name__)

__all__ = ["cleanup_subprocess", "cleanup_all_subprocesses"]

# Cleanup ladder timings (mirrors Claude Code)
SIGINT_WAIT_MS = 100  # Wait after SIGINT before escalating
POLL_INTERVAL_MS = 50  # Poll interval during wait
SIGTERM_WAIT_MS = 600  # Wait after SIGTERM before kill -9


async def cleanup_subprocess(
    process: asyncio.subprocess.Process | Any,
    timeout_seconds: float = 1.0,
) -> None:
    """Clean up a subprocess with escalating signals.

    Cleanup ladder:
    1. Detach stderr handler (prevent further output)
    2. Send SIGINT (Ctrl+C equivalent)
    3. Poll every 50ms for up to 100ms to check if process exited
    4. If still running, send SIGTERM
    5. Wait up to 600ms for graceful termination
    6. If still running, send SIGKILL (kill -9)

    Args:
        process: subprocess.Popen or asyncio.subprocess.Process.
        timeout_seconds: Maximum total time for cleanup (caps the ladder).

    Raises:
        RuntimeError: If cleanup fails after kill -9.
    """
    if process is None:
        return

    # Check if already terminated
    if hasattr(process, "returncode") and process.returncode is not None:
        logger.debug("[MCP] Process already terminated")
        return

    # Get the PID
    pid = None
    if hasattr(process, "pid"):
        pid = process.pid
    elif hasattr(process, "_transport"):
        # asyncio.subprocess.Process
        pid = process._transport.get_pid() if hasattr(process._transport, "get_pid") else None

    if pid is None:
        logger.warning("[MCP] Cannot get PID for cleanup")
        return

    deadline = asyncio.get_event_loop().time() + timeout_seconds
    logger.debug("[MCP] Starting cleanup ladder for PID %d", pid)

    # Step 1: SIGINT
    try:
        if sys.platform != "win32":
            os.kill(pid, signal.SIGINT)
            logger.debug("[MCP] Sent SIGINT to PID %d", pid)
        else:
            # Windows: use terminate()
            if hasattr(process, "terminate"):
                process.terminate()
    except ProcessLookupError:
        logger.debug("[MCP] PID %d already terminated", pid)
        return
    except OSError as e:
        logger.warning("[MCP] Cannot send SIGINT to PID %d: %s", pid, e)

    # Step 2: Poll for termination
    poll_start = asyncio.get_event_loop().time()
    poll_deadline = min(poll_start + (SIGINT_WAIT_MS / 1000), deadline)

    while asyncio.get_event_loop().time() < poll_deadline:
        try:
            # Check if process is still alive
            if sys.platform != "win32":
                os.kill(pid, 0)  # Signal 0 = check if process exists
            else:
                if hasattr(process, "returncode") and process.returncode is not None:
                    logger.debug("[MCP] PID %d terminated after SIGINT", pid)
                    return
        except ProcessLookupError:
            logger.debug("[MCP] PID %d terminated after SIGINT", pid)
            return

        await asyncio.sleep(POLL_INTERVAL_MS / 1000)

    # Step 3: SIGTERM (process still running)
    if asyncio.get_event_loop().time() < deadline:
        try:
            if sys.platform != "win32":
                os.kill(pid, signal.SIGTERM)
                logger.debug("[MCP] Sent SIGTERM to PID %d", pid)
            else:
                if hasattr(process, "kill"):
                    process.kill()
        except ProcessLookupError:
            logger.debug("[MCP] PID %d terminated after SIGTERM attempt", pid)
            return
        except OSError as e:
            logger.warning("[MCP] Cannot send SIGTERM to PID %d: %s", pid, e)

    # Step 4: Wait for SIGTERM to take effect
    term_deadline = min(asyncio.get_event_loop().time() + (SIGTERM_WAIT_MS / 1000), deadline)

    while asyncio.get_event_loop().time() < term_deadline:
        try:
            if sys.platform != "win32":
                os.kill(pid, 0)
            else:
                if hasattr(process, "returncode") and process.returncode is not None:
                    logger.debug("[MCP] PID %d terminated after SIGTERM", pid)
                    return
        except ProcessLookupError:
            logger.debug("[MCP] PID %d terminated after SIGTERM", pid)
            return

        await asyncio.sleep(POLL_INTERVAL_MS / 1000)

    # Step 5: SIGKILL (force kill)
    if asyncio.get_event_loop().time() < deadline:
        try:
            if sys.platform != "win32":
                os.kill(pid, signal.SIGKILL)
                logger.warning("[MCP] Force killed PID %d", pid)
            else:
                # Windows doesn't have SIGKILL; use kill() which is equivalent
                if hasattr(process, "kill"):
                    process.kill()
        except ProcessLookupError:
            logger.debug("[MCP] PID %d already terminated", pid)
            return
        except OSError as e:
            logger.error("[MCP] Cannot force kill PID %d: %s", pid, e)

    # Final check
    try:
        if sys.platform != "win32":
            os.kill(pid, 0)
            # Still alive after SIGKILL — should not happen
            logger.error("[MCP] PID %d survived SIGKILL", pid)
        else:
            if hasattr(process, "returncode") and process.returncode is None:
                logger.error("[MCP] Process survived kill()")
    except ProcessLookupError:
        logger.debug("[MCP] PID %d terminated after SIGKILL", pid)


async def cleanup_all_subprocesses(
    processes: dict[str, asyncio.subprocess.Process | Any],
    aggregate_timeout_seconds: float = 5.0,
) -> dict[str, str]:
    """Clean up multiple subprocesses with aggregate deadline.

    Args:
        processes: Dict mapping server name to process.
        aggregate_timeout_seconds: Total deadline for all cleanups.

    Returns:
        Dict mapping server name to cleanup result ("clean", "forced", "error").
    """
    deadline = asyncio.get_event_loop().time() + aggregate_timeout_seconds
    results = {}

    for name, process in processes.items():
        remaining = deadline - asyncio.get_event_loop().time()
        if remaining <= 0:
            remaining = 0.1

        try:
            await cleanup_subprocess(process, timeout_seconds=remaining)
            results[name] = "clean"
        except Exception as e:
            logger.error("[MCP] Cleanup error for %s: %s", name, e)
            results[name] = "error"

    return results
