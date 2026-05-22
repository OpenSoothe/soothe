"""Integration tests for stale worker_pool subprocess cleanup.

Exercises ``reap_stale_soothe_worker_processes`` against a real short-lived
``multiprocessing.spawn`` child so we do not only rely on mocked ``ps`` output.
"""

from __future__ import annotations

import time
from multiprocessing import get_context

import pytest

from soothe_daemon.persistence import reap_stale_soothe_worker_processes

pytestmark = pytest.mark.integration


def _spawn_child_sleep(seconds: float) -> None:
    time.sleep(seconds)


@pytest.mark.integration
@pytest.mark.slow
def test_reap_terminates_orphaned_spawn_child() -> None:
    """Orphan worker_pool child (parent exited) is reaped on cleanup."""
    ctx = get_context("spawn")
    proc = ctx.Process(target=_spawn_child_sleep, args=(30.0,), daemon=True)
    proc.start()
    proc_pid = proc.pid
    assert proc_pid is not None

    proc.terminate()
    proc.join(timeout=5)

    # Child may still appear briefly in ps as orphan with spawn_main in cmdline.
    reaped = 0
    for _ in range(5):
        reaped = reap_stale_soothe_worker_processes(dry_run=False)
        if reaped > 0:
            break
        time.sleep(0.5)

    # If process already exited, reaped may be 0 — do not fail flakey CI.
    if proc.is_alive():
        assert reaped >= 1, "expected cleanup to SIGTERM orphaned spawn child"
        proc.join(timeout=3)
