"""Execute-step AI ledger compaction at write time."""

from __future__ import annotations

from pathlib import Path

from soothe.foundation.context.engine import ContextEngine
from soothe.foundation.context.persistence.sqlite_backend import SqliteContextPersistence
from soothe.foundation.sloop.utils.messages import (
    LoopAIMessage,
    LoopHumanMessage,
    _record_ledger_message,
    compact_execute_ai_message,
)


def test_compact_execute_ai_message_uses_trim_messages() -> None:
    long_text = "word " * 5000
    msg = LoopAIMessage(content=long_text, phase="execute_step", thread_id="t")
    compact = compact_execute_ai_message(msg, max_tokens=2048)
    assert compact is not msg
    assert len(str(compact.content)) < len(long_text)


def test_record_ledger_message_compacts_execute_ai_via_ce_cap() -> None:
    ce = ContextEngine(
        persistence=SqliteContextPersistence(loop_id="test", db_path=Path(":memory:"))
    )
    ce.execute_ai_ledger_max_tokens = 2048
    long_text = "token " * 5000
    ai = LoopAIMessage(content=long_text, phase="execute_step", thread_id="t")
    _record_ledger_message(ce, ai, "execute_step")
    stored = ce.ledger.get_messages(phases=["execute_step"])[0]
    assert len(str(stored.content)) < len(long_text)


def test_record_ledger_message_skips_compaction_for_human() -> None:
    ce = ContextEngine(
        persistence=SqliteContextPersistence(loop_id="test", db_path=Path(":memory:"))
    )
    ce.execute_ai_ledger_max_tokens = 2048
    human = LoopHumanMessage(content="task", phase="execute_step", thread_id="t")
    _record_ledger_message(ce, human, "execute_step")
    stored = ce.ledger.get_messages(phases=["execute_step"])[0]
    assert stored.content == "task"
