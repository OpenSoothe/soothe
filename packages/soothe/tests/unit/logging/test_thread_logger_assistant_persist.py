"""ThreadLogger persistence of loop-tagged assistant output (RFC-413 resume parity).

When the loop emits ``loop_assistant_messages_chunk`` for ``plan_direct`` or
``goal_completion`` (LEDGER_DIRECT strategy), the text never reaches the
LangGraph checkpoint. ``ThreadLogger`` must persist it as a ``kind=conversation,
role=assistant`` row so ``LoopCardManager._derive_cards`` →
``card_binder.collect_cognition_card_replay`` can surface it on resume.
"""

from __future__ import annotations

import json
from pathlib import Path

from langchain_core.messages import AIMessage, AIMessageChunk

from soothe.logging.thread_logger import ThreadLogger


def _read_jsonl(path: Path) -> list[dict]:
    rows: list[dict] = []
    if not path.exists():
        return rows
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def test_full_loop_ai_message_with_plan_direct_phase_persists_as_conversation_row(
    tmp_path: Path,
) -> None:
    logger = ThreadLogger(thread_dir=str(tmp_path), thread_id="t1")
    msg = AIMessage(content="I will complete this request directly: do thing")
    msg.phase = "plan_direct"

    logger.log(namespace=(), mode="messages", data=(msg, {}))
    logger._flush_buffer()  # type: ignore[attr-defined]

    rows = _read_jsonl(logger.log_path)
    conv = [r for r in rows if r.get("kind") == "conversation"]
    assert len(conv) == 1
    assert conv[0]["role"] == "assistant"
    assert conv[0]["phase"] == "plan_direct"
    assert conv[0]["text"].startswith("I will complete this request directly")


def test_full_loop_ai_message_with_goal_completion_phase_persists(tmp_path: Path) -> None:
    logger = ThreadLogger(thread_dir=str(tmp_path), thread_id="t2")
    msg = AIMessage(content="Result\n\n| col |\nTotal: 42")
    msg.phase = "goal_completion"

    logger.log(namespace=(), mode="messages", data=(msg, {}))
    logger._flush_buffer()  # type: ignore[attr-defined]

    rows = _read_jsonl(logger.log_path)
    conv = [r for r in rows if r.get("kind") == "conversation" and r.get("role") == "assistant"]
    assert len(conv) == 1
    assert conv[0]["phase"] == "goal_completion"
    assert "Total: 42" in conv[0]["text"]


def test_streaming_ai_chunk_is_not_persisted_as_conversation_row(tmp_path: Path) -> None:
    """SYNTHESIZE chunks are already accumulated into a goal_completion AIMessage
    appended to ``state.loop_messages`` by the orchestrator. Logging each chunk
    here would create one conversation row per token — never the desired output.
    """
    logger = ThreadLogger(thread_dir=str(tmp_path), thread_id="t3")
    chunk = AIMessageChunk(content="partial token ")
    chunk.phase = "goal_completion"

    logger.log(namespace=(), mode="messages", data=(chunk, {}))
    logger._flush_buffer()  # type: ignore[attr-defined]

    rows = _read_jsonl(logger.log_path)
    conv = [r for r in rows if r.get("kind") == "conversation"]
    assert conv == []


def test_ai_message_without_loop_phase_is_not_persisted_as_conversation(tmp_path: Path) -> None:
    logger = ThreadLogger(thread_dir=str(tmp_path), thread_id="t4")
    msg = AIMessage(content="generic assistant text")
    # No phase → CoreAgent output we do not want to mirror into the activity log.

    logger.log(namespace=(), mode="messages", data=(msg, {}))
    logger._flush_buffer()  # type: ignore[attr-defined]

    rows = _read_jsonl(logger.log_path)
    assert [r for r in rows if r.get("kind") == "conversation"] == []


def test_tail_records_stay_buffered_without_explicit_flush(tmp_path: Path) -> None:
    """Tail records stick in the buffer if no further write triggers the flush.

    The buffer flushes on (a) >=100 records OR (b) >=1 second since last flush
    AND a new write happens. After a loop ends, no new writes arrive on that
    thread — so the goal_completion conversation row and the trailing
    ``log_assistant_response`` row both stay in memory unless the caller
    explicitly invokes ``flush()`` (which is exactly what the engine's
    stream-finally block now does).
    """
    logger = ThreadLogger(thread_dir=str(tmp_path), thread_id="tail")

    # First write triggers a flush (initial condition); make a second write
    # after the interval so the buffer is empty going into the tail writes.
    import time

    logger._write_record({"timestamp": "t1", "kind": "event", "data": {"x": 1}})
    time.sleep(1.05)
    logger._write_record({"timestamp": "t2", "kind": "event", "data": {"x": 2}})

    # Tail writes: arrive within the 1s interval, no further writes follow.
    msg = AIMessage(content="FINAL ANSWER")
    msg.phase = "goal_completion"
    logger.log(namespace=(), mode="messages", data=(msg, {}))
    logger.log_assistant_response("FINAL ANSWER")

    # Snapshot disk WITHOUT calling flush(): the tail rows must still be in
    # memory. Without the engine.py change, this is what resume sees.
    rows_on_disk = _read_jsonl(logger.log_path)
    conv_rows = [r for r in rows_on_disk if r.get("kind") == "conversation"]
    assert conv_rows == [], "tail records must be stuck in buffer before flush()"
    assert len(logger._buffer) == 2  # type: ignore[attr-defined]

    # The engine's flush call lands the tail records on disk.
    logger.flush()
    rows_after_flush = _read_jsonl(logger.log_path)
    conv_rows_after = [r for r in rows_after_flush if r.get("kind") == "conversation"]
    assert len(conv_rows_after) == 2
    assert conv_rows_after[0]["phase"] == "goal_completion"
    assert conv_rows_after[0]["text"] == "FINAL ANSWER"


def test_phase_tagged_row_does_not_get_overwritten_by_legacy_concat(tmp_path: Path) -> None:
    """Document the resume duality the engine fix relies on.

    When a phase-tagged ``goal_completion`` row exists, the engine must SKIP
    the legacy ``log_assistant_response("".join(full_response))`` call,
    because that legacy row historically concatenates plan_direct text +
    ToolMessage outputs + goal_completion fragments into one malformed
    untyped assistant card. This test asserts that the two writes are
    distinguishable on disk: the phase-tagged row carries ``phase``, the
    legacy row does not — so the engine's ``phase_tagged_assistant_written``
    flag can suppress one without affecting the other.
    """
    logger = ThreadLogger(thread_dir=str(tmp_path), thread_id="dual")
    msg = AIMessage(content="## Result\n```\n42 files\n```")
    msg.phase = "goal_completion"

    # 1) Phase-tagged write (the new path)
    logger.log(namespace=(), mode="messages", data=(msg, {}))

    # 2) Legacy concat write (the bug the engine flag suppresses)
    logger.log_assistant_response(
        "I will do thing"  # plan_direct
        "raw tool output 1"
        "raw tool output 2"
        "## Result\n```\n42 files\n```"  # goal_completion fragment
    )

    logger.flush()
    rows = _read_jsonl(logger.log_path)
    assistant_rows = [
        r for r in rows if r.get("kind") == "conversation" and r.get("role") == "assistant"
    ]
    assert len(assistant_rows) == 2
    tagged = [r for r in assistant_rows if r.get("phase") == "goal_completion"]
    legacy = [r for r in assistant_rows if not r.get("phase")]
    assert len(tagged) == 1
    assert len(legacy) == 1
    # The phase-tagged row is clean, the legacy is the jammed-together text.
    assert tagged[0]["text"] == "## Result\n```\n42 files\n```"
    assert "raw tool output" in legacy[0]["text"]
    # The engine's job is to NOT call log_assistant_response when phase-tagged
    # rows exist; this test guarantees the two are distinguishable on disk
    # so that suppression is well-defined.


def test_ai_message_with_tool_calls_logs_tool_call_only_not_conversation(tmp_path: Path) -> None:
    logger = ThreadLogger(thread_dir=str(tmp_path), thread_id="t5")
    msg = AIMessage(
        content="calling tool",
        tool_calls=[{"id": "tc1", "name": "run_command", "args": {"command": "ls"}}],
    )
    msg.phase = "goal_completion"  # would otherwise trigger the conversation path

    logger.log(namespace=(), mode="messages", data=(msg, {}))
    logger._flush_buffer()  # type: ignore[attr-defined]

    rows = _read_jsonl(logger.log_path)
    assert any(r.get("kind") == "tool_call" for r in rows)
    # tool-bearing assistant messages are not user-visible final text, so no
    # conversation row should be written even when the phase matches.
    assert not any(r.get("kind") == "conversation" for r in rows)
