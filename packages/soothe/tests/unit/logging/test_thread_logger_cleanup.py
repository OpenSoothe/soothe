"""Tests for ``cleanup_stale_thread_logs`` against ``threads/{id}/logs/`` layout."""

from __future__ import annotations

import os
import time
from pathlib import Path

from soothe.logging.thread_logger import cleanup_stale_thread_logs


def _make_thread_log(root: Path, thread_id: str, *, content: str = "{}\n") -> Path:
    log_path = root / thread_id / "logs" / "conversation.jsonl"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text(content, encoding="utf-8")
    return log_path


def test_age_based_cleanup_deletes_old_logs_under_logs_subdir(tmp_path: Path) -> None:
    old_log = _make_thread_log(tmp_path, "old-thread")
    fresh_log = _make_thread_log(tmp_path, "fresh-thread")

    old_mtime = time.time() - (40 * 86400)
    os.utime(old_log, (old_mtime, old_mtime))

    deleted = cleanup_stale_thread_logs(
        retention_days=30,
        max_size_mb=100,
        threads_root=tmp_path,
    )

    assert deleted == 1
    assert not old_log.exists()
    assert not (tmp_path / "old-thread").exists()
    assert fresh_log.exists()


def test_size_budget_deletes_oldest_first(tmp_path: Path) -> None:
    older = _make_thread_log(tmp_path, "t-older", content="x" * 1500)
    newer = _make_thread_log(tmp_path, "t-newer", content="y" * 1500)

    now = time.time()
    os.utime(older, (now - 100, now - 100))
    os.utime(newer, (now - 10, now - 10))

    # Budget smaller than either file alone forces at least one delete;
    # oldest goes first until under budget.
    deleted = cleanup_stale_thread_logs(
        retention_days=30,
        max_size_mb=0.002,  # ~2097 bytes
        threads_root=tmp_path,
    )

    assert deleted >= 1
    assert not older.exists()
    assert newer.exists()


def test_return_count_includes_age_and_size_deletes(tmp_path: Path) -> None:
    aged = _make_thread_log(tmp_path, "aged", content="a" * 100)
    keep = _make_thread_log(tmp_path, "keep", content="b" * 100)
    pressure_a = _make_thread_log(tmp_path, "pressure-a", content="c" * 1200)
    pressure_b = _make_thread_log(tmp_path, "pressure-b", content="d" * 1200)

    old_mtime = time.time() - (60 * 86400)
    os.utime(aged, (old_mtime, old_mtime))
    now = time.time()
    os.utime(pressure_a, (now - 50, now - 50))
    os.utime(pressure_b, (now - 5, now - 5))
    os.utime(keep, (now - 1, now - 1))

    deleted = cleanup_stale_thread_logs(
        retention_days=30,
        max_size_mb=0.002,  # ~2097 bytes — keep (100) + one pressure file may fit
        threads_root=tmp_path,
    )

    assert deleted >= 2  # aged + at least one size-pressure victim
    assert not aged.exists()
    assert keep.exists()
