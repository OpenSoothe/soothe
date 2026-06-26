"""LangGraph execute stream namespace helpers (IG-514 / RFC-628)."""


def _execute_namespace_segment(ns_key: tuple[str, ...]) -> str:
    if len(ns_key) != 1:
        return ""
    return str(ns_key[0] or "").strip()


def is_execute_namespace_key(ns_key: tuple[str, ...]) -> bool:
    """True when namespace is a single ``execute:…`` segment (root or nested ``/N``)."""
    segment = _execute_namespace_segment(ns_key)
    return bool(segment) and segment.startswith("execute:")


def is_root_execute_namespace_key(ns_key: tuple[str, ...]) -> bool:
    """True for root CoreAgent execute namespace ``execute:{run_id}`` only."""
    segment = _execute_namespace_segment(ns_key)
    if not segment.startswith("execute:"):
        return False
    suffix = segment[len("execute:") :]
    return "/" not in suffix


def is_step_level_execute_namespace_key(ns_key: tuple[str, ...]) -> bool:
    """True when tools belong to the plan-step graph, not ``tools:`` subagent subgraphs."""
    return is_execute_namespace_key(ns_key)


__all__ = [
    "is_execute_namespace_key",
    "is_root_execute_namespace_key",
    "is_step_level_execute_namespace_key",
]
