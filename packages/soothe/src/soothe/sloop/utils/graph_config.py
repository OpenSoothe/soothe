"""RunnableConfig helpers for nested graph invocations."""

from __future__ import annotations

from typing import Any

# Parent checkpoint *coordinates* must not leak into child graph configs;
# the *checkpointer* itself must — the execution twin graph is compiled
# without one (lazy pool init) and receives it via the config.
_PARENT_COORDINATE_KEYS = ("checkpoint_ns", "checkpoint_id", "checkpoint_map")


def strip_parent_checkpoint_coordinates(config: dict[str, Any]) -> dict[str, Any]:
    """Drop inherited parent-graph checkpoint coordinates from a config.

    Merging the ambient parent config (`langgraph.config.get_config` — e.g.
    the StrangeLoop execute-node config, whose `checkpoint_ns` is
    `execute:{task_id}`) into a CoreAgent stream config makes the CoreAgent
    run as a parent subgraph: its checkpoints — including interrupts — land
    under the parent's task namespace instead of the thread root, so
    `Command(resume=...)` cannot reach them. Tracing callbacks and
    the config-injected checkpointer are preserved; only the coordinate keys
    are removed.
    """
    conf = config.get("configurable")
    if not isinstance(conf, dict):
        return config
    for key in _PARENT_COORDINATE_KEYS:
        conf.pop(key, None)
    return config
