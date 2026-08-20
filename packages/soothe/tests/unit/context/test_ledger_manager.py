"""Tests for LedgerManager (soothe.context.ledger)."""

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from soothe.context.ledger import LedgerManager, _LedgerEntry


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


class TestLedgerClear:
    def test_clear_removes_all(self) -> None:
        lm = LedgerManager()
        lm.record_message(HumanMessage(content="hi"), phase="plan")
        lm.clear()
        assert lm.get_messages() == []


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
