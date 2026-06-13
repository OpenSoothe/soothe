"""Helpers aligning PostgreSQL pool sizes with daemon thread_pool settings."""


def recommended_sloop_pool_size(*, max_thread_workers: int) -> int:
    """Size the StrangeLoop singleton for concurrent thread-pool workers.

    Rule: ``max_workers + 2`` headroom for the utility runner and bursts, capped at 32.
    """
    return min(32, max(4, max_thread_workers + 2))


def recommended_checkpointer_pool_size(*, max_thread_workers: int) -> int:
    """Size the shared LangGraph checkpointer pool (one singleton per process)."""
    return min(16, max(2, (max_thread_workers + 1) // 2 + 2))


__all__ = ["recommended_sloop_pool_size", "recommended_checkpointer_pool_size"]
