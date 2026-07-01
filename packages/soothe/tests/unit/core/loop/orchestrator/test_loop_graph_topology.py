"""Loop Graph node topology (RFC-220)."""

from unittest.mock import MagicMock

from soothe.foundation.sloop.orchestrator.builder import build_strange_loop_graph


def test_strange_loop_graph_exposes_rfc220_named_nodes() -> None:
    """Compiled graph includes normative node ids from RFC-220 §Loop Graph Topology."""
    ctx = MagicMock()
    compiled = build_strange_loop_graph(ctx)
    graph = compiled.get_graph()
    names = set(graph.nodes)

    for required in (
        "init_or_resume",
        "iteration_gate",
        "iteration_start",
        "bounded_evidence_gather",
        "plan_assess",
        "plan_generate",
        "goal_completion",
        "resolve_decision",
        "validate_evidence_bindings",
        "execute",
        "record_iteration",
    ):
        assert required in names, f"missing node {required}: {sorted(names)}"
