"""Loop Graph node topology (RFC-220)."""

from unittest.mock import MagicMock

from soothe.sloop.orchestrator.builder import build_strange_loop_graph


def test_strange_loop_graph_exposes_rfc220_named_nodes() -> None:
    """Compiled graph includes normative node ids from RFC-220 §Loop Graph Topology."""
    ctx = MagicMock()
    compiled = build_strange_loop_graph(ctx)
    graph = compiled.get_graph()
    names = set(graph.nodes)

    for required in (
        "enter_loop",
        "check_limits",
        "begin_iteration",
        "gather_evidence",
        "assess",
        "generate_plan",
        "finalize",
        "commit_plan",
        "validate_plan",
        "execute",
        "record_progress",
    ):
        assert required in names, f"missing node {required}: {sorted(names)}"
