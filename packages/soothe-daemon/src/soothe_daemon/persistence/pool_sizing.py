"""Helpers aligning PostgreSQL pool sizes with daemon thread_pool settings."""


def recommended_checkpoints_pool_size(*, max_thread_workers: int) -> int:
    """Size the unified checkpoints pool for concurrent thread-pool workers.

    Rule: ``max_workers + 2`` headroom for the utility runner and bursts, capped at 32.
    """
    return min(32, max(4, max_thread_workers + 2))


__all__ = ["recommended_checkpoints_pool_size"]
