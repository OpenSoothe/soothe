"""Shared SootheConfig builders for unit and integration tests."""

from __future__ import annotations

import logging
from typing import Any

from soothe.config.models import ModelRouter, RouterProfile
from soothe.config.settings import SootheConfig

logger = logging.getLogger(__name__)


def config_with_router_profile(
    router: ModelRouter | dict[str, Any] | None = None,
    *,
    profile_name: str = "test",
    embedding_dims: int = 1536,
    **kwargs: Any,
) -> SootheConfig:
    """Build ``SootheConfig`` with a single router profile."""
    if not router:
        return SootheConfig(**kwargs)
    if isinstance(router, dict):
        router = ModelRouter(**router)
    embedding_profile = kwargs.pop(
        "embedding_profile",
        [{"model_role": "openai:text-embedding-3-small", "embedding_dims": embedding_dims}],
    )
    return SootheConfig(
        router_profiles=[
            RouterProfile(
                name=profile_name,
                router=router,
            )
        ],
        embedding_profile=embedding_profile,
        active_router_profile=profile_name,
        **kwargs,
    )


def reset_pool_singletons(agent_mod: Any, registry_cls: Any) -> None:
    """Reset all PostgreSQL pool singleton references.

    Stops pool worker threads and nullifies all singleton references so
    subsequent tests create fresh pools. We avoid calling the full
    ``AsyncConnectionPool.close()`` because it can hang indefinitely on dead
    sockets (psycopg C extension ignores asyncio cancellation). Instead, we
    signal the worker to stop and mark the pool as closed, which prevents the
    event loop teardown from hanging on pending pool tasks.
    """
    pools_to_reset: list[Any] = []

    registry = registry_cls.try_get_instance()
    if registry is not None:
        pools_to_reset.extend(registry._pools.values())
    if getattr(agent_mod, "_shared_pool", None) is not None:
        pools_to_reset.append(agent_mod._shared_pool)

    import soothe_nano.resolve.shared_checkpointer_pool as nano_cp_mod

    if getattr(nano_cp_mod, "_shared_checkpointer_pool", None) is not None:
        pools_to_reset.append(nano_cp_mod._shared_checkpointer_pool)

    # Signal worker threads to stop and mark pools as closed.
    for pool in pools_to_reset:
        if pool is None:
            continue
        try:
            pool._signal_stop_worker()  # type: ignore[attr-defined]
        except Exception:
            pass
        try:
            pool._closed = True  # type: ignore[attr-defined]
        except Exception:
            pass

    registry_cls.reset_instance()
    agent_mod._shared_pool = None

    # Reset the asyncio.Lock so a locked lock from a prior test doesn't block
    # the next get_shared_instance() call. With session-scoped event loop,
    # the lock persists across tests.
    import asyncio as _asyncio

    agent_mod._pool_lock = _asyncio.Lock()

    nano_cp_mod._shared_checkpointer_pool = None
    nano_cp_mod._checkpointer_setup_done = False
    nano_cp_mod._setup_waiter = None
