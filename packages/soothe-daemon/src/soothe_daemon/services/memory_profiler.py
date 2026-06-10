"""Memory profiling service using tracemalloc (IG-475, IG-477).

Provides real-time memory inspection via tracemalloc with:
- HTTP endpoints for snapshot comparison and top allocations
- Automatic periodic logging of memory growth
- Integration with daemon lifecycle
- IG-477: Large allocation sampling (captures multi-MB objects)
- IG-477: Queue depth metrics for stream backpressure debugging

tracemalloc is chosen over objgraph/meliae because:
- Built-in to Python 3.4+ (no external dependencies)
- Low overhead (~5-10% performance impact)
- Shows allocation source (file/line) and traceback chains
- Supports snapshot comparison for leak detection
"""

from __future__ import annotations

import gc
import logging
import os
import tracemalloc
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import psutil

if TYPE_CHECKING:
    from soothe_daemon.config.models import MemoryProfilingConfig

logger = logging.getLogger(__name__)

# IG-477: Minimum size for "large allocation" sampling (KB)
LARGE_ALLOCATION_THRESHOLD_KB = 100.0


class MemoryProfiler:
    """Memory profiling service using tracemalloc (IG-475, IG-477).

    Start/stop integrates with daemon lifecycle. Provides methods for
    taking snapshots, comparing allocations, and getting memory stats.

    IG-477 additions:
    - `get_large_allocations()`: Captures multi-MB objects that standard
      statistics("lineno") misses due to count-based aggregation
    - `get_queue_metrics()`: Reports response queue depths for diagnosing
      stream backpressure issues

    Args:
        config: MemoryProfilingConfig with tracing parameters.
    """

    def __init__(self, config: MemoryProfilingConfig) -> None:
        self._config = config
        self._running = False
        self._last_snapshot: tracemalloc.Snapshot | None = None
        self._last_rss_mb: float = 0.0
        self._last_timestamp: datetime | None = None
        self._process = psutil.Process(os.getpid())

    def start(self) -> None:
        """Start tracemalloc tracing.

        Called during daemon startup when memory_profiling.enabled=true.
        """
        if self._running:
            return

        tracemalloc.start(self._config.trace_depth)
        self._running = True
        self._last_snapshot = tracemalloc.take_snapshot()
        self._last_rss_mb = self._process.memory_info().rss / 1024 / 1024
        self._last_timestamp = datetime.now(UTC)

        logger.info(
            "[MemoryProfiler] Started tracemalloc (depth=%d, pid=%d, initial RSS=%.1f MB)",
            self._config.trace_depth,
            os.getpid(),
            self._last_rss_mb,
        )

    def stop(self) -> None:
        """Stop tracemalloc tracing.

        Called during daemon shutdown.
        """
        if not self._running:
            return

        tracemalloc.stop()
        self._running = False
        self._last_snapshot = None
        logger.info("[MemoryProfiler] Stopped tracemalloc")

    def is_running(self) -> bool:
        """Return True if tracemalloc is active."""
        return self._running and tracemalloc.is_tracing()

    def take_snapshot(self) -> tracemalloc.Snapshot:
        """Take a new tracemalloc snapshot.

        Returns:
            Current memory allocation snapshot.
        """
        if not self._running:
            raise RuntimeError("MemoryProfiler not running")
        return tracemalloc.take_snapshot()

    def get_current_stats(self) -> dict[str, Any]:
        """Get current memory statistics.

        Returns:
            Dict with RSS, VSZ, tracemalloc tracked size, and top allocations.
        """
        mem_info = self._process.memory_info()
        rss_mb = mem_info.rss / 1024 / 1024
        vsz_mb = mem_info.vms / 1024 / 1024

        result: dict[str, Any] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "pid": os.getpid(),
            "rss_mb": round(rss_mb, 2),
            "vsz_mb": round(vsz_mb, 2),
            "tracing_enabled": self._running,
        }

        if self._running and tracemalloc.is_tracing():
            current_snapshot = tracemalloc.take_snapshot()
            traced_current, traced_peak = tracemalloc.get_traced_memory()

            result["tracemalloc_traced_mb"] = round(traced_current / 1024 / 1024, 2)
            result["tracemalloc_peak_mb"] = round(traced_peak / 1024 / 1024, 2)

            # Top allocations by size
            top_stats = current_snapshot.statistics("lineno")
            top_allocations = []
            for stat in top_stats[: self._config.top_allocations_limit]:
                top_allocations.append(
                    {
                        "file": str(stat.traceback[-1].filename),
                        "line": stat.traceback[-1].lineno,
                        "size_kb": round(stat.size / 1024, 2),
                        "count": stat.count,
                    }
                )
            result["top_allocations_by_line"] = top_allocations

            # Top allocations by traceback
            top_by_trace = current_snapshot.statistics("traceback")
            top_tracebacks = []
            for stat in top_by_trace[:10]:
                tb_lines = [f"{t.filename}:{t.lineno}" for t in stat.traceback]
                top_tracebacks.append(
                    {
                        "traceback": tb_lines,
                        "size_kb": round(stat.size / 1024, 2),
                        "count": stat.count,
                    }
                )
            result["top_allocations_by_traceback"] = top_tracebacks

            # IG-477: Large allocations (>100KB) ranked by size
            result["large_allocations"] = self.get_large_allocations(
                snapshot=current_snapshot, min_size_kb=LARGE_ALLOCATION_THRESHOLD_KB
            )

            # Compare with last snapshot if available
            if self._last_snapshot is not None:
                diff = current_snapshot.compare_to(self._last_snapshot, "lineno")
                growth = []
                for stat in diff[:20]:
                    growth.append(
                        {
                            "file": str(stat.traceback[-1].filename),
                            "line": stat.traceback[-1].lineno,
                            "size_diff_kb": round(stat.size_diff / 1024, 2),
                            "count_diff": stat.count_diff,
                        }
                    )
                result["growth_since_last"] = growth

        return result

    def get_large_allocations(
        self,
        snapshot: tracemalloc.Snapshot | None = None,
        min_size_kb: float = LARGE_ALLOCATION_THRESHOLD_KB,
    ) -> list[dict[str, Any]]:
        """Get allocations larger than threshold, ranked by size.

        IG-477: This captures large single objects (multi-MB strings/buffers)
        that statistics("lineno") misses because it groups by count.

        Args:
            snapshot: Snapshot to analyze (takes new if None).
            min_size_kb: Minimum allocation size to include (default 100KB).

        Returns:
            List of large allocations with traceback, size, and count.
        """
        if not self._running:
            return []

        if snapshot is None:
            snapshot = tracemalloc.take_snapshot()

        # Use traceback grouping to see full allocation chain
        stats = snapshot.statistics("traceback")

        large_allocs = []
        for stat in stats:
            size_kb = stat.size / 1024
            if size_kb >= min_size_kb:
                tb_lines = [f"{t.filename}:{t.lineno}" for t in stat.traceback]
                large_allocs.append(
                    {
                        "size_kb": round(size_kb, 2),
                        "count": stat.count,
                        "traceback": tb_lines,
                        "avg_size_kb": round(size_kb / max(stat.count, 1), 2),
                    }
                )

        # Sort by size descending
        large_allocs.sort(key=lambda x: x["size_kb"], reverse=True)
        return large_allocs[: self._config.top_allocations_limit]

    def get_queue_metrics(self) -> dict[str, Any]:
        """Get queue depths from thread pool for backpressure debugging.

        IG-477: Reports response queue depths to diagnose stream backpressure
        issues. When queues are near capacity (100), it indicates client
        delivery is slower than worker production.

        Returns:
            Dict with pending_responses count and per-worker queue metrics.
        """
        try:
            from soothe_daemon.runner.thread_runner import ThreadPool
        except ImportError:
            return {"error": "ThreadPool module not available"}

        pool = ThreadPool._shared_pool
        if pool is None:
            return {"error": "ThreadPool not initialized", "hint": "No queries have run yet"}

        metrics: dict[str, Any] = {
            "pending_responses_count": len(pool._pending_responses),
            "workers_by_loop_count": len(pool._workers_by_loop_id),
            "workers": {},
            "config": {
                "response_queue_maxsize": 100,  # IG-477: hardcoded bound
            },
        }

        for worker_id, worker in pool._workers.items():
            worker_metrics = {
                "status": worker.status.value,
                "current_loop_id": worker.current_loop_id,
                "current_request_id": worker.current_request_id,
                "requests_completed": worker.requests_completed,
                "is_alive": worker.is_alive(),
            }

            # Get queue depth - threading.Queue.qsize() is approximate
            try:
                worker_metrics["response_queue_qsize"] = worker.response_queue.qsize()
            except Exception:
                worker_metrics["response_queue_qsize"] = "error"

            metrics["workers"][worker_id] = worker_metrics

        # Summary stats
        queue_sizes = [
            w.get("response_queue_qsize", 0)
            for w in metrics["workers"].values()
            if isinstance(w.get("response_queue_qsize"), int)
        ]
        if queue_sizes:
            metrics["summary"] = {
                "max_queue_depth": max(queue_sizes),
                "avg_queue_depth": round(sum(queue_sizes) / len(queue_sizes), 2),
                "workers_near_capacity": sum(1 for q in queue_sizes if q >= 90),
            }

        return metrics

    def get_object_counts(self) -> dict[str, int]:
        """Get counts of Python objects by type using gc.get_objects().

        Returns:
            Dict mapping type name to count for top 30 object types.
        """
        gc.collect()
        from collections import Counter

        type_counts = Counter(type(o).__name__ for o in gc.get_objects())
        return dict(type_counts.most_common(30))

    def compare_snapshots(
        self,
        old_snapshot: tracemalloc.Snapshot | None = None,
        new_snapshot: tracemalloc.Snapshot | None = None,
    ) -> dict[str, Any]:
        """Compare two snapshots and return allocation differences.

        Args:
            old_snapshot: Earlier snapshot (uses last_snapshot if None).
            new_snapshot: Later snapshot (takes new if None).

        Returns:
            Dict with growth statistics and per-allocation changes.
        """
        if not self._running:
            raise RuntimeError("MemoryProfiler not running")

        if old_snapshot is None:
            old_snapshot = self._last_snapshot
        if old_snapshot is None:
            raise ValueError("No old snapshot available")

        if new_snapshot is None:
            new_snapshot = tracemalloc.take_snapshot()

        diff = new_snapshot.compare_to(old_snapshot, "lineno")
        growth: list[dict[str, Any]] = []
        shrinkage: list[dict[str, Any]] = []

        for stat in diff:
            entry = {
                "file": str(stat.traceback[-1].filename),
                "line": stat.traceback[-1].lineno,
                "size_diff_kb": round(stat.size_diff / 1024, 2),
                "count_diff": stat.count_diff,
            }
            if stat.size_diff > 0:
                growth.append(entry)
            else:
                shrinkage.append(entry)

        # Sort by size diff magnitude
        growth.sort(key=lambda x: abs(x["size_diff_kb"]), reverse=True)
        shrinkage.sort(key=lambda x: abs(x["size_diff_kb"]), reverse=True)

        return {
            "timestamp": datetime.now(UTC).isoformat(),
            "growth_count": len(growth),
            "shrinkage_count": len(shrinkage),
            "net_size_diff_kb": round(
                sum(s["size_diff_kb"] for s in growth) + sum(s["size_diff_kb"] for s in shrinkage),
                2,
            ),
            "top_growth": growth[: self._config.top_allocations_limit],
            "top_shrinkage": shrinkage[: self._config.top_allocations_limit],
        }

    def update_last_snapshot(self) -> None:
        """Update last snapshot and check for growth logging threshold."""
        if not self._running:
            return

        new_snapshot = tracemalloc.take_snapshot()
        new_rss_mb = self._process.memory_info().rss / 1024 / 1024

        # Check growth threshold
        if self._last_rss_mb > 0:
            growth_mb = new_rss_mb - self._last_rss_mb
            if growth_mb >= self._config.log_growth_threshold_mb:
                logger.warning(
                    "[MemoryProfiler] RSS grew by %.1f MB (%.1f → %.1f MB) "
                    "exceeding threshold of %d MB",
                    growth_mb,
                    self._last_rss_mb,
                    new_rss_mb,
                    self._config.log_growth_threshold_mb,
                )
                # Log top growth sources
                if self._last_snapshot is not None:
                    diff = new_snapshot.compare_to(self._last_snapshot, "lineno")
                    for stat in diff[:5]:
                        if stat.size_diff > 1024 * 100:  # > 100 KB growth
                            logger.warning(
                                "[MemoryProfiler] Growth source: %s:%d (+%.1f KB, %d objects)",
                                stat.traceback[-1].filename,
                                stat.traceback[-1].lineno,
                                stat.size_diff / 1024,
                                stat.count_diff,
                            )

        self._last_snapshot = new_snapshot
        self._last_rss_mb = new_rss_mb
        self._last_timestamp = datetime.now(UTC)

    def force_gc_and_report(self) -> dict[str, Any]:
        """Force garbage collection and report collected objects.

        Returns:
            Dict with GC statistics and memory before/after.
        """
        before_rss = self._process.memory_info().rss / 1024 / 1024

        # Run all GC generations
        gc.collect()
        gc.collect()
        gc.collect()

        after_rss = self._process.memory_info().rss / 1024 / 1024

        gc_stats = {
            "collections": gc.get_stats(),
            "garbage_count": len(gc.garbage),
        }

        result = {
            "timestamp": datetime.now(UTC).isoformat(),
            "rss_before_mb": round(before_rss, 2),
            "rss_after_mb": round(after_rss, 2),
            "rss_reclaimed_mb": round(before_rss - after_rss, 2),
            "gc_stats": gc_stats,
        }

        logger.info(
            "[MemoryProfiler] Forced GC: reclaimed %.1f MB (%.1f → %.1f MB)",
            result["rss_reclaimed_mb"],
            before_rss,
            after_rss,
        )

        return result


__all__ = ["MemoryProfiler", "LARGE_ALLOCATION_THRESHOLD_KB"]
