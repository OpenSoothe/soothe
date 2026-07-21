"""LangGraph execute stream namespace helpers.

Namespace classification for tool stamping and TUI routing:

| Namespace pattern           | Classification | Tool prefix | TUI routing       |
|-----------------------------|----------------|-------------|-------------------|
| ('execute:run_id',)         | Root execute   | s:          | Step card         |
| ('execute:run_id', '1')     | Parallel branch| s:          | Step card         |
| ('execute:run_id', 'tools:')| Subgraph       | t{n}:       | SubAgent card     |
| ('tools:...',)              | Subgraph       | t{n}:       | SubAgent card     |

Parallel steps use two-element namespaces where the second element
is an integer branch index, NOT a subgraph namespace like 'tools:*'.
These must be classified as step-level (s: prefix) to display on step cards.
"""


def _first_segment(ns_key: tuple[str, ...]) -> str:
    """Return the first namespace segment (stripped)."""
    if not ns_key:
        return ""
    return str(ns_key[0] or "").strip()


def is_parallel_branch_namespace(ns_key: tuple[str, ...]) -> bool:
    """True for parallel step branch namespaces like ``('execute:{run_id}', '1')``.

    Parallel execution assigns integer branch indices (0, 1, 2, ...) as the
    second namespace element, distinguishing parallel branches from subgraph
    delegation which uses ``tools:`` or other named namespaces.

    Args:
        ns_key: Namespace tuple from stream event.

    Returns:
        True if this is a parallel branch (execute:* + integer suffix).
    """
    if len(ns_key) != 2:
        return False
    first = _first_segment(ns_key)
    if not first.startswith("execute:"):
        return False
    second = str(ns_key[1] or "").strip()
    # Branch index is pure integer string (LangGraph parallel pattern)
    return second.isdigit()


def is_execute_namespace_key(ns_key: tuple[str, ...]) -> bool:
    """True when namespace is a single ``execute:…`` segment (root or nested ``/N``).

    Note: This does NOT include parallel branch namespaces like ('execute:*', '1').
    Use ``is_step_level_execute_namespace_key`` for step-level classification.
    """
    if len(ns_key) != 1:
        return False
    segment = _first_segment(ns_key)
    return bool(segment) and segment.startswith("execute:")


def is_root_execute_namespace_key(ns_key: tuple[str, ...]) -> bool:
    """True for root CoreAgent execute namespace ``execute:{run_id}`` only.

    Excludes:
    - Parallel branches ('execute:*', 'N')
    - Nested subgraph namespaces ('execute:*', 'tools:*')
    - Inline nested execute ('execute:run_id/N')
    """
    if not is_execute_namespace_key(ns_key):
        return False
    segment = _first_segment(ns_key)
    suffix = segment[len("execute:") :]
    return "/" not in suffix


def is_step_level_execute_namespace_key(ns_key: tuple[str, ...]) -> bool:
    """True when tools belong to the plan-step graph, not ``tools:`` subagent subgraphs.

    This includes BOTH:
    - Root execute namespaces ('execute:{run_id}',)
    - Parallel branch namespaces ('execute:{run_id}', 'N')

    Both should receive ``s:`` tool prefix (step-level) because there is no
    ``task`` delegation row - the tools run directly on the step card.

    Args:
        ns_key: Namespace tuple from stream event.

    Returns:
        True if tools from this namespace should be stamped with ``s:`` prefix.
    """
    # Single-element execute namespace (root)
    if is_execute_namespace_key(ns_key):
        return True
    # Two-element parallel branch namespace (execute:* + integer)
    if is_parallel_branch_namespace(ns_key):
        return True
    return False


__all__ = [
    "is_execute_namespace_key",
    "is_parallel_branch_namespace",
    "is_root_execute_namespace_key",
    "is_step_level_execute_namespace_key",
]
