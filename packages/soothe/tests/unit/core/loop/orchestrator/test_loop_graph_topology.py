"""Loop Graph node topology (RFC-904 decompose cutover)."""

from unittest.mock import MagicMock

from soothe.sloop.orchestrator.builder import build_strange_loop_graph


def test_strange_loop_graph_exposes_rfc904_named_nodes() -> None:
    """Compiled graph includes DISPATCH / RECONCILE / ROOT_EVAL stations."""
    ctx = MagicMock()
    compiled = build_strange_loop_graph(ctx)
    graph = compiled.get_graph()
    names = set(graph.nodes)

    for required in (
        "intake",
        "enter_loop",
        "dispatch",
        "execute",
        "record_progress",
        "reconcile",
        "root_eval",
        "finalize",
        "await_user",
        "delegate",
    ):
        assert required in names, f"missing node {required}: {sorted(names)}"

    # Legacy plan spine is no longer on the live graph.
    for removed in (
        "gather_evidence",
        "evaluate",
        "generate_plan",
        "commit_plan",
        "check_limits",
        "begin_iteration",
        "validate_plan",
    ):
        assert removed not in names, f"legacy node still present: {removed}"
