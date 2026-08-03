"""Append-only LoopRail rule-fire trace (job-scoped).

Memory backend for tests; JSONL file backend for SQLite-mode jobs.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol


@dataclass
class GuardResult:
    """Structured guard evaluation outcome (RFC-630)."""

    matched: bool
    confidence: float = 1.0
    reasoning: str = ""


@dataclass
class RuleFireRecord:
    """One append-only rail trace row."""

    timestamp: datetime
    rule_id: str | None
    event: str
    condition: str | None
    guard_result: GuardResult
    builtin: str | None
    builtin_result: str | None = None
    goal_id: str | None = None
    seq: int = 0

    def to_dict(self) -> dict[str, Any]:
        """Serialize for JSONL / evaluation export."""
        payload = asdict(self)
        payload["timestamp"] = self.timestamp.isoformat()
        return payload


class RailTraceStore(Protocol):
    """Job-scoped append-only trace writer/reader."""

    def append(self, job_id: str, record: RuleFireRecord) -> RuleFireRecord:
        """Append a record; assign monotonic seq; return stored record."""

    def read(self, job_id: str) -> list[RuleFireRecord]:
        """Return all records for a job in seq order."""


@dataclass
class MemoryRailTraceStore:
    """In-memory trace store (integration tests / default harness)."""

    _records: dict[str, list[RuleFireRecord]] = field(default_factory=dict)

    def append(self, job_id: str, record: RuleFireRecord) -> RuleFireRecord:
        bucket = self._records.setdefault(job_id, [])
        record.seq = len(bucket)
        bucket.append(record)
        return record

    def read(self, job_id: str) -> list[RuleFireRecord]:
        return list(self._records.get(job_id, ()))


@dataclass
class JsonlRailTraceStore:
    """Append-only JSONL file under a job artifact directory."""

    root: Path

    def _path(self, job_id: str) -> Path:
        return self.root / job_id / "rail_trace.jsonl"

    def append(self, job_id: str, record: RuleFireRecord) -> RuleFireRecord:
        path = self._path(job_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        existing = self.read(job_id)
        record.seq = len(existing)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record.to_dict(), ensure_ascii=False) + "\n")
        return record

    def read(self, job_id: str) -> list[RuleFireRecord]:
        path = self._path(job_id)
        if not path.is_file():
            return []
        out: list[RuleFireRecord] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            raw = json.loads(line)
            gr = raw.get("guard_result") or {}
            out.append(
                RuleFireRecord(
                    timestamp=datetime.fromisoformat(raw["timestamp"]),
                    rule_id=raw.get("rule_id"),
                    event=raw["event"],
                    condition=raw.get("condition"),
                    guard_result=GuardResult(
                        matched=bool(gr.get("matched")),
                        confidence=float(gr.get("confidence", 1.0)),
                        reasoning=str(gr.get("reasoning", "")),
                    ),
                    builtin=raw.get("builtin"),
                    builtin_result=raw.get("builtin_result"),
                    goal_id=raw.get("goal_id"),
                    seq=int(raw.get("seq", len(out))),
                )
            )
        return out


def export_trace_evaluation(
    job_id: str,
    store: RailTraceStore,
    *,
    expected_builtins: list[str] | None = None,
) -> dict[str, Any]:
    """Build an evaluation report for a job's rail trace.

    Args:
        job_id: Job root goal id.
        store: Trace store to read.
        expected_builtins: Optional ordered list of successful builtin invocations.

    Returns:
        JSON-serializable evaluation dict.
    """
    records = store.read(job_id)
    fired_builtins = [
        r.builtin
        for r in records
        if r.builtin and r.guard_result.matched and r.builtin_result == "success"
    ]
    expected = expected_builtins or []
    matches = fired_builtins == expected if expected else None
    return {
        "job_id": job_id,
        "record_count": len(records),
        "fired_builtins": fired_builtins,
        "expected_builtins": expected,
        "builtins_match_expected": matches,
        "records": [r.to_dict() for r in records],
        "evaluated_at": datetime.now(UTC).isoformat(),
    }
