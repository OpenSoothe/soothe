"""Tests for job-scoped rail_trace path + legacy loops migrate (IG-686)."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from soothe.autopilot.rail.trace_store import GuardResult, JsonlRailTraceStore, RuleFireRecord


def _record() -> RuleFireRecord:
    return RuleFireRecord(
        timestamp=datetime.now(UTC),
        rule_id="r1",
        event="goal_completed",
        condition="done",
        guard_result=GuardResult(matched=True),
        builtin="complete_job",
        builtin_result="success",
        goal_id="abcd1234",
    )


def test_jsonl_writes_under_jobs_root(tmp_path: Path) -> None:
    store = JsonlRailTraceStore(root=tmp_path / "jobs")
    store.append("abcd1234", _record())
    path = tmp_path / "jobs" / "abcd1234" / "rail_trace.jsonl"
    assert path.is_file()
    assert len(store.read("abcd1234")) == 1


def test_migrates_legacy_loops_path_on_read(tmp_path: Path) -> None:
    legacy = tmp_path / "loops" / "abcd1234" / "rail_trace.jsonl"
    legacy.parent.mkdir(parents=True)
    legacy.write_text(
        '{"timestamp":"2026-08-05T00:00:00+00:00","rule_id":"r1","event":"x",'
        '"condition":null,"guard_result":{"matched":true,"confidence":1.0,'
        '"reasoning":""},"builtin":null,"builtin_result":null,"goal_id":null,'
        '"seq":0}\n',
        encoding="utf-8",
    )
    store = JsonlRailTraceStore(root=tmp_path / "jobs", legacy_root=tmp_path / "loops")
    records = store.read("abcd1234")
    assert len(records) == 1
    assert records[0].event == "x"
    assert (tmp_path / "jobs" / "abcd1234" / "rail_trace.jsonl").is_file()
