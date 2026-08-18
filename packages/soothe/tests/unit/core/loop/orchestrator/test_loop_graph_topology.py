"""Loop Graph node topology (RFC-220, revised by RFC-903 P3)."""

from unittest.mock import MagicMock

from soothe.sloop.orchestrator.builder import build_strange_loop_graph


def test_strange_loop_graph_exposes_rfc220_named_nodes() -> None:
    """Compiled graph includes normative node ids from RFC-220 §Loop Graph Topology.

    RFC-903 P3: ``begin_iteration`` folded into ``check_limits`` and
    ``validate_plan`` folded into ``commit_plan``. The graph no longer
    exposes those two as separate nodes; their logic lives inside the
    folding nodes' ``process``/``post`` stages.
    """
    ctx = MagicMock()
    compiled = build_strange_loop_graph(ctx)
    graph = compiled.get_graph()
    names = set(graph.nodes)

    for required in (
        "enter_loop",
        "check_limits",
        "gather_evidence",
        "evaluate",
        "generate_plan",
        "finalize",
        "commit_plan",
        "execute",
        "record_progress",
    ):
        assert required in names, f"missing node {required}: {sorted(names)}"

    # RFC-903 P3: folded nodes are no longer graph nodes.
    assert "begin_iteration" not in names
    assert "validate_plan" not in names
    assert "assess" not in names
    assert "analyze_gaps" not in names
