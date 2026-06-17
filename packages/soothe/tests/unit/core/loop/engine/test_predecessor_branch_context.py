"""Unit tests for parallel branch predecessor ledger replay (RFC-214)."""

from __future__ import annotations

from soothe.foundation.loop.engine.predecessor_branch_context import (
    DEFAULT_BRANCH_PREDECESSOR_MAX_MESSAGES,
    predecessor_execute_messages_for_branch,
    transitive_dependency_step_ids,
)
from soothe.foundation.loop.state.schemas import AgentDecision, StepAction
from soothe.foundation.loop.utils.messages import LoopAIMessage, LoopHumanMessage


def test_transitive_dependency_step_ids_diamond() -> None:
    """Transitive closure includes all DAG predecessors (shared fan-in)."""
    s_a = StepAction(id="A", description="a", expected_output="o")
    s_b = StepAction(id="B", description="b", expected_output="o", dependencies=["A"])
    s_c = StepAction(id="C", description="c", expected_output="o", dependencies=["A"])
    s_d = StepAction(id="D", description="d", expected_output="o", dependencies=["B", "C"])
    d = AgentDecision(
        type="execute_steps",
        steps=[s_a, s_b, s_c, s_d],
        execution_mode="dependency",
        reasoning="r",
    )
    assert transitive_dependency_step_ids(s_d, d) == frozenset({"A", "B", "C"})


def test_transitive_dependency_step_ids_empty_when_no_dependencies() -> None:
    step = StepAction(id="solo", description="s", expected_output="o", dependencies=None)
    decision = AgentDecision(
        type="execute_steps",
        steps=[step],
        execution_mode="parallel",
        reasoning="r",
    )
    assert transitive_dependency_step_ids(step, decision) == frozenset()


def test_predecessor_execute_messages_empty_predecessor_ids() -> None:
    assert predecessor_execute_messages_for_branch([], frozenset()) == []


def test_predecessor_execute_messages_max_messages_zero_means_unlimited() -> None:
    ledger = [
        LoopHumanMessage(content="h", phase="execute_step", step_id="A"),
        LoopAIMessage(content="a", phase="execute_step", step_id="A"),
    ]
    out = predecessor_execute_messages_for_branch(ledger, frozenset({"A"}), max_messages=0)
    assert len(out) == 2
    assert [m.content for m in out] == ["h", "a"]


def test_predecessor_execute_messages_step_id_from_additional_kwargs() -> None:
    """Ledger rows may carry step_id only in LangChain additional_kwargs."""
    ledger = [
        LoopHumanMessage(
            content="hx",
            phase="execute_step",
            additional_kwargs={"step_id": "K"},
        ),
        LoopAIMessage(
            content="ax",
            phase="execute_step",
            additional_kwargs={"step_id": "K"},
        ),
    ]
    out = predecessor_execute_messages_for_branch(ledger, frozenset({"K"}), max_messages=10)
    assert len(out) == 2
    assert out[0].content == "hx"
    assert out[1].content == "ax"


def test_predecessor_execute_messages_skips_non_execute_phase() -> None:
    ledger = [
        LoopHumanMessage(content="plan", phase="plan_generate", step_id="A"),
        LoopHumanMessage(content="h", phase="execute_step", step_id="A"),
        LoopAIMessage(content="a", phase="execute_step", step_id="A"),
    ]
    out = predecessor_execute_messages_for_branch(ledger, frozenset({"A"}), max_messages=10)
    assert [m.content for m in out] == ["h", "a"]


def test_predecessor_execute_messages_multiple_predecessor_steps_in_order() -> None:
    ledger = [
        LoopHumanMessage(content="hA", phase="execute_step", step_id="A"),
        LoopAIMessage(content="aA", phase="execute_step", step_id="A"),
        LoopHumanMessage(content="hC", phase="execute_step", step_id="C"),
        LoopAIMessage(content="aC", phase="execute_step", step_id="C"),
    ]
    out = predecessor_execute_messages_for_branch(ledger, frozenset({"A", "C"}), max_messages=20)
    assert [m.content for m in out] == ["hA", "aA", "hC", "aC"]


def test_transitive_dependency_step_ids_chain() -> None:
    s1 = StepAction(id="A", description="1", expected_output="o")
    s2 = StepAction(id="B", description="2", expected_output="o", dependencies=["A"])
    s3 = StepAction(id="C", description="3", expected_output="o", dependencies=["B"])
    d = AgentDecision(
        type="execute_steps",
        steps=[s1, s2, s3],
        execution_mode="dependency",
        reasoning="r",
    )
    assert transitive_dependency_step_ids(s3, d) == frozenset({"A", "B"})


def test_transitive_dependency_includes_external_dep_string() -> None:
    """Model may cite a completed id not present as its own StepAction row."""
    s2 = StepAction(id="B", description="2", expected_output="o", dependencies=["Z99"])
    d = AgentDecision(
        type="execute_steps",
        steps=[s2],
        execution_mode="parallel",
        reasoning="r",
    )
    assert transitive_dependency_step_ids(s2, d) == frozenset({"Z99"})


def test_predecessor_execute_messages_order_and_filter() -> None:
    ledger: list = [
        LoopHumanMessage(content="p", phase="plan_generate"),
        LoopHumanMessage(content="h1", phase="execute_step", step_id="A", thread_id="t"),
        LoopAIMessage(content="a1", phase="execute_step", step_id="A", thread_id="t"),
        LoopHumanMessage(content="h2", phase="execute_step", step_id="B", thread_id="t"),
        LoopAIMessage(content="a2", phase="execute_step", step_id="B", thread_id="t"),
    ]
    out = predecessor_execute_messages_for_branch(ledger, frozenset({"B"}), max_messages=99)
    assert len(out) == 2
    assert out[0].content == "h2"
    assert out[1].content == "a2"
    assert out[0] is not ledger[3]


def test_predecessor_execute_messages_respects_max_messages() -> None:
    ledger = []
    for i in range(5):
        ledger.append(LoopHumanMessage(content=f"h{i}", phase="execute_step", step_id="X"))
        ledger.append(LoopAIMessage(content=f"a{i}", phase="execute_step", step_id="X"))
    out = predecessor_execute_messages_for_branch(ledger, frozenset({"X"}), max_messages=3)
    assert len(out) == 3


def test_default_cap_constant_sane() -> None:
    assert DEFAULT_BRANCH_PREDECESSOR_MAX_MESSAGES >= 32
