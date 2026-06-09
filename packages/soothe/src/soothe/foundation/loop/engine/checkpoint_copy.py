"""Checkpoint thread copy via public BaseCheckpointSaver API (RFC-223).

LangGraph's ``BaseCheckpointSaver.acopy_thread`` is documented in the
protocol but every concrete saver in the current LangGraph release
(``InMemorySaver``, ``AsyncSqliteSaver``, ``AsyncPostgresSaver``, ...)
inherits the base ``raise NotImplementedError``. This module supplies a
generic implementation built on the public ``alist`` + ``aput`` +
``aput_writes`` surface that every saver does implement, so RFC-223
checkpoint forking works on any saver we use.

Semantics: copy every checkpoint tuple from ``source_thread_id`` to a new
namespace under ``target_thread_id``. The target thread sees the source's
full conversation history; subsequent writes from the agent running on
``target_thread_id`` go into the new namespace and don't pollute the source.

Caveats:
- Source checkpoints are read most-recent-first by ``alist`` and replayed
  oldest-first so parent_config links stay consistent.
- Each tuple's ``pending_writes`` (mid-step writes) are also replayed via
  ``aput_writes``. In practice forks happen between steps when no pending
  writes exist, but copying them anyway is the conservative choice.
- ``new_versions`` for ``aput`` is reconstructed as an empty mapping. The
  saved checkpoint already encodes channel versions; ``new_versions`` only
  represents the **delta** for incremental writes, which is empty when we
  re-put a complete pre-existing checkpoint.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from langchain_core.runnables import RunnableConfig
    from langgraph.checkpoint.base import BaseCheckpointSaver

logger = logging.getLogger(__name__)


def _swap_thread_id(config: RunnableConfig | None, new_thread_id: str) -> RunnableConfig:
    """Return a shallow copy of ``config`` with ``configurable.thread_id`` replaced.

    Returns an empty dict when ``config`` is None so callers can pass it
    straight to ``aput`` without conditional logic.
    """
    if not config:
        return {}  # type: ignore[return-value]
    new_config = dict(config)
    configurable = dict(new_config.get("configurable", {}))
    configurable["thread_id"] = new_thread_id
    new_config["configurable"] = configurable
    return new_config  # type: ignore[return-value]


async def copy_thread_via_public_api(
    saver: BaseCheckpointSaver,
    source_thread_id: str,
    target_thread_id: str,
) -> int:
    """Copy every checkpoint from ``source_thread_id`` to ``target_thread_id``.

    Args:
        saver: Any LangGraph BaseCheckpointSaver instance (sqlite/postgres/in-memory).
        source_thread_id: Thread to read checkpoints from.
        target_thread_id: Thread to write the copied checkpoints under.

    Returns:
        The number of checkpoint tuples copied (zero when source is empty).
    """
    if source_thread_id == target_thread_id:
        # No-op: same thread, nothing to do.
        return 0

    source_config: RunnableConfig = {"configurable": {"thread_id": source_thread_id}}  # type: ignore[assignment]

    # Materialize tuples first so we can reverse them. ``alist`` yields most-
    # recent-first; ``aput`` requires oldest-first to preserve parent links.
    tuples: list[Any] = []
    async for tup in saver.alist(source_config):
        tuples.append(tup)

    if not tuples:
        logger.debug(
            "copy_thread: source %s has no checkpoints; target %s left empty",
            source_thread_id,
            target_thread_id,
        )
        return 0

    tuples.reverse()

    for tup in tuples:
        new_config = _swap_thread_id(tup.config, target_thread_id)
        # The saved checkpoint already encodes complete channel versions —
        # ``new_versions`` for aput is the *delta* for an incremental write
        # and should be empty when re-puting a pre-existing checkpoint.
        await saver.aput(new_config, tup.checkpoint, tup.metadata, {})

        # Replay pending writes (intermediate task writes attached to this
        # checkpoint). Most forks happen at step boundaries with no pending
        # writes, but we copy them when present for correctness.
        pending_writes = getattr(tup, "pending_writes", None) or []
        if pending_writes:
            # pending_writes shape: list[tuple[task_id, channel, value]]
            # Group by task_id so each aput_writes call carries one task's writes.
            by_task: dict[str, list[tuple[str, Any]]] = {}
            for entry in pending_writes:
                # CheckpointTuple.pending_writes is documented as
                # list[tuple[str, str, Any]] = (task_id, channel, value)
                if len(entry) < 3:
                    continue
                task_id, channel, value = entry[0], entry[1], entry[2]
                by_task.setdefault(task_id, []).append((channel, value))
            for task_id, writes in by_task.items():
                await saver.aput_writes(new_config, writes, task_id)

    logger.debug(
        "copy_thread: copied %d checkpoint(s) %s → %s",
        len(tuples),
        source_thread_id,
        target_thread_id,
    )
    return len(tuples)
