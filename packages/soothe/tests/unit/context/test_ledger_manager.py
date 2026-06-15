"""Tests for LedgerManager (soothe.context.ledger)."""

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from soothe.foundation.context.ledger import LedgerManager, _LedgerEntry


class TestLedgerRecordAndRetrieve:
    def test_record_and_get_all(self) -> None:
        lm = LedgerManager()
        lm.record_message(HumanMessage(content="hello"), phase="plan")
        lm.record_message(AIMessage(content="world"), phase="execute_step")
        msgs = lm.get_messages()
        assert len(msgs) == 2
        assert msgs[0].content == "hello"
        assert msgs[1].content == "world"

    def test_filter_by_phase(self) -> None:
        lm = LedgerManager()
        lm.record_message(HumanMessage(content="plan"), phase="plan")
        lm.record_message(HumanMessage(content="exec"), phase="execute_step")
        lm.record_message(AIMessage(content="result"), phase="execute_step")
        exec_msgs = lm.get_messages(phases=["execute_step"])
        assert len(exec_msgs) == 2

    def test_empty_phases_returns_all(self) -> None:
        lm = LedgerManager()
        lm.record_message(HumanMessage(content="hi"), phase="plan")
        assert len(lm.get_messages(phases=None)) == 1


class TestLedgerProjectForPlan:
    def test_no_bounding_returns_all(self) -> None:
        lm = LedgerManager()
        for i in range(10):
            lm.record_message(HumanMessage(content=f"msg{i}"), phase="plan")
        result = lm.project_for_plan()
        assert len(result) == 10

    def test_max_messages(self) -> None:
        lm = LedgerManager()
        for i in range(10):
            lm.record_message(HumanMessage(content=f"msg{i}"), phase="plan")
        result = lm.project_for_plan(max_messages=3)
        assert len(result) == 3
        assert result[0].content == "msg7"

    def test_max_per_message_chars(self) -> None:
        lm = LedgerManager()
        lm.record_message(HumanMessage(content="x" * 200), phase="plan")
        result = lm.project_for_plan(max_per_message_chars=50)
        assert len(result[0].content) <= 50

    def test_max_total_chars(self) -> None:
        lm = LedgerManager()
        for i in range(5):
            lm.record_message(HumanMessage(content="a" * 100), phase="plan")
        result = lm.project_for_plan(max_total_chars=150)
        total = sum(len(m.content) for m in result)
        assert total <= 150


class TestLedgerProjectForCoreAgent:
    def test_returns_execute_step_and_unphased(self) -> None:
        lm = LedgerManager()
        lm.record_message(HumanMessage(content="plan"), phase="plan")
        lm.record_message(HumanMessage(content="exec"), phase="execute_step")
        lm.record_message(AIMessage(content="result"), phase="execute_step")
        lm.record_message(HumanMessage(content="no-phase"), phase=None)
        result = lm.project_for_core_agent()
        assert len(result) == 3
        assert "plan" not in [m.content for m in result]

    def test_excludes_non_execute_phases(self) -> None:
        lm = LedgerManager()
        lm.record_message(HumanMessage(content="plan"), phase="plan")
        lm.record_message(HumanMessage(content="validate"), phase="validate")
        assert lm.project_for_core_agent() == []


class TestLedgerStepResult:
    def test_success_with_output(self) -> None:
        lm = LedgerManager()
        lm.record_step_result("S1", "Do thing", "done", None, True)
        text = lm.render_for_reason()
        assert "[S1] ✓" in text
        assert "Do thing" in text
        assert "done" in text

    def test_success_no_output(self) -> None:
        lm = LedgerManager()
        lm.record_step_result("S1", "Do thing", None, None, True)
        text = lm.render_for_reason()
        assert "(no text output)" in text

    def test_failure(self) -> None:
        lm = LedgerManager()
        lm.record_step_result("S1", "Do thing", None, "timeout", False)
        text = lm.render_for_reason()
        assert "[S1] ✗" in text
        assert "timeout" in text

    def test_render_truncates(self) -> None:
        lm = LedgerManager()
        for i in range(100):
            lm.record_step_result(f"S{i}", f"Step {i}", f"Output {'x' * 50}", None, True)
        text = lm.render_for_reason(max_chars=200)
        assert len(text) <= 200


class TestLedgerClear:
    def test_clear_removes_all(self) -> None:
        lm = LedgerManager()
        lm.record_message(HumanMessage(content="hi"), phase="plan")
        lm.record_step_result("S1", "Step", "out", None, True)
        lm.clear()
        assert lm.get_messages() == []
        assert lm.render_for_reason() == ""


class TestLedgerEntries:
    def test_entries_returns_tuples(self) -> None:
        lm = LedgerManager()
        lm.record_message(HumanMessage(content="hello"), phase="execute_step")
        lm.record_message(AIMessage(content="world"), phase="plan_assess")
        entries = lm.entries()
        assert len(entries) == 2
        assert entries[0][1] == "execute_step"
        assert entries[1][1] == "plan_assess"

    def test_entries_with_phase_filter(self) -> None:
        lm = LedgerManager()
        lm.record_message(HumanMessage(content="exec"), phase="execute_step")
        lm.record_message(HumanMessage(content="plan"), phase="plan_assess")
        entries = lm.entries(phases=["execute_step"])
        assert len(entries) == 1
        assert entries[0][1] == "execute_step"

    def test_entries_no_phases_returns_all(self) -> None:
        lm = LedgerManager()
        lm.record_message(HumanMessage(content="hi"), phase="plan")
        assert len(lm.entries()) == 1


class TestLedgerCompaction:
    def test_no_compact_below_max(self) -> None:
        lm = LedgerManager(max_entries=10)
        for i in range(5):
            lm.record_message(HumanMessage(content=f"msg{i}"), phase="test")
        assert len(lm.entries()) == 5

    def test_compact_drops_without_fn(self) -> None:
        lm = LedgerManager(max_entries=5)
        for i in range(10):
            lm.record_message(HumanMessage(content=f"msg{i}"), phase="test")
        # 10 > 5, compact triggered, oldest 5 dropped
        entries = lm.entries()
        assert len(entries) <= 6  # 5 kept + potentially one compacted summary

    def test_compact_with_fn(self) -> None:
        def summarize(old_entries: list[_LedgerEntry]) -> str:
            return f"Summarized {len(old_entries)} messages"

        lm = LedgerManager(max_entries=5, compact_fn=summarize)
        for i in range(10):
            lm.record_message(HumanMessage(content=f"msg{i}"), phase="test")
        entries = lm.entries()
        # Should have 1 compacted SystemMessage + 5 most recent = 6
        assert len(entries) == 6
        assert entries[0][1] == "compacted"
        assert isinstance(entries[0][0], SystemMessage)
        assert "Summarized" in entries[0][0].content

    def test_compact_fn_returns_none_drops_entries(self) -> None:
        def no_op(old_entries: list[_LedgerEntry]) -> str | None:
            return None

        lm = LedgerManager(max_entries=5, compact_fn=no_op)
        for i in range(10):
            lm.record_message(HumanMessage(content=f"msg{i}"), phase="test")
        entries = lm.entries()
        assert len(entries) == 5

    def test_compact_fn_error_drops_entries(self) -> None:
        def bad_fn(old_entries: list[_LedgerEntry]) -> str:
            raise RuntimeError("compaction failed")

        lm = LedgerManager(max_entries=5, compact_fn=bad_fn)
        for i in range(10):
            lm.record_message(HumanMessage(content=f"msg{i}"), phase="test")
        entries = lm.entries()
        assert len(entries) == 5
