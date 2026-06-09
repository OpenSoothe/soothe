"""Plan-phase ledger projection (IG-380)."""

from __future__ import annotations

from langchain_core.messages import HumanMessage

from soothe.config.models import PlanPromptLedgerConfig
from soothe.foundation.loop.utils.messages import LoopAIMessage, LoopHumanMessage
from soothe.foundation.loop.prompts.plan_ledger_projection import project_loop_messages_for_plan


def _msgs(n: int) -> list:
    out = []
    for i in range(n):
        out.append(
            LoopHumanMessage(content=f"H{i}", thread_id="t", iteration=0, phase="execute_step")
        )
        out.append(
            LoopAIMessage(content=f"A{i}" * 50, thread_id="t", iteration=0, phase="execute_step")
        )
    return out


def test_projection_disabled_returns_shallow_copy_same_len() -> None:
    raw = _msgs(2)
    cfg = PlanPromptLedgerConfig(
        plan_ledger_max_messages=0,
        plan_ledger_max_total_chars=0,
        plan_ledger_max_message_chars=0,
    )
    proj = project_loop_messages_for_plan(raw, cfg)
    assert len(proj) == len(raw)
    assert proj is not raw
    assert proj[0] is raw[0]


def test_projection_tail_max_messages() -> None:
    raw = _msgs(5)
    cfg = PlanPromptLedgerConfig(plan_ledger_max_messages=4)
    proj = project_loop_messages_for_plan(raw, cfg)
    assert len(proj) == 4
    assert "H1" not in extract_join(proj)  # oldest pair dropped
    assert "[Earlier ledger content omitted" in proj[0].content


def test_projection_does_not_mutate_original() -> None:
    raw = [LoopHumanMessage(content="x" * 200, thread_id="t", iteration=0, phase="execute_step")]
    cfg = PlanPromptLedgerConfig(plan_ledger_max_message_chars=20)
    proj = project_loop_messages_for_plan(raw, cfg)
    assert len(proj[0].content) < len(raw[0].content)
    assert len(raw[0].content) == 200


def test_projection_max_total_chars_drops_oldest() -> None:
    raw = [
        LoopHumanMessage(content="H", thread_id="t", iteration=0, phase="execute_step"),
        LoopAIMessage(content="A" * 100, thread_id="t", iteration=0, phase="execute_step"),
        LoopHumanMessage(content="H2", thread_id="t", iteration=0, phase="execute_step"),
        LoopAIMessage(content="B" * 10, thread_id="t", iteration=0, phase="execute_step"),
    ]
    cfg = PlanPromptLedgerConfig(plan_ledger_max_total_chars=30)
    proj = project_loop_messages_for_plan(raw, cfg)
    joined = extract_join(proj)
    assert "H2" in joined or "BBBB" in joined
    assert len(proj) <= len(raw)


def extract_join(msgs: list) -> str:
    return "".join(getattr(m, "content", "") or "" for m in msgs)


def test_projection_none_cfg_passthrough() -> None:
    raw = [HumanMessage(content="only")]
    proj = project_loop_messages_for_plan(raw, None)
    assert len(proj) == 1
    assert proj[0] is raw[0]
