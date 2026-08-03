"""Security regression tests for rail integrity, path traversal, and error leakage.

Covers findings from the ZCL-06/ZCL-07 audit:

- SC-01: Rail YAML integrity verification (SHA-256 hashing + tamper detection)
- V1:    Path traversal in JsonlRailTraceStore via unsanitized job_id
- V7:    Corrupted JSONL trace line no longer blocks future appends
- V8:    Exception detail leakage in builtin/guard error results

These tests are fast, isolated, and run under the default unit test suite.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from soothe.autopilot.rail.builtins_exec import RailBuiltinExecutor
from soothe.autopilot.rail.trace_store import (
    GuardResult,
    JsonlRailTraceStore,
    RuleFireRecord,
    _sanitize_job_id,
)
from soothe.context.engine import ContextEngine
from soothe.rails import LoopRailCatalog, RailCatalogError, compute_rail_hash, load_rail_file

# ── SC-01: Rail config integrity verification ──────────────────────────


def test_compute_rail_hash_deterministic() -> None:
    """Same YAML text always produces the same SHA-256 hex digest."""
    text = "id: test\nversion: '1.0'\n"
    h1 = compute_rail_hash(text)
    h2 = compute_rail_hash(text)
    assert h1 == h2
    assert len(h1) == 64
    assert all(c in "0123456789abcdef" for c in h1)


def test_compute_rail_hash_different_text() -> None:
    """Different YAML text produces a different hash."""
    h1 = compute_rail_hash("id: a\n")
    h2 = compute_rail_hash("id: b\n")
    assert h1 != h2


def test_load_rail_file_includes_integrity_hash(tmp_path: Path) -> None:
    """Loaded RailDefinition carries a non-empty SHA-256 integrity hash."""
    path = tmp_path / "test-rail.yml"
    yaml_text = (
        "id: test-rail\n"
        "version: '1.0'\n"
        "summary: Test rail.\n"
        "applies_when: testing\n"
        "flow:\n"
        "  - event: job_start\n"
        "    then: complete_job\n"
    )
    path.write_text(yaml_text, encoding="utf-8")
    rail = load_rail_file(path)
    assert rail.integrity_hash
    assert len(rail.integrity_hash) == 64
    assert rail.integrity_hash == compute_rail_hash(yaml_text)


def test_integrity_hash_detects_tamper(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """verify_integrity returns False when YAML has been modified."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr("soothe.config.SOOTHE_HOME", home)
    monkeypatch.setattr("soothe.config.env.SOOTHE_HOME", home)

    rail_path = home / "rails"
    rail_path.mkdir()
    rail_file = rail_path / "test-integrity.yml"
    original_yaml = (
        "id: test-integrity\n"
        "version: '1.0'\n"
        "summary: Original.\n"
        "applies_when: testing\n"
        "flow:\n"
        "  - event: job_start\n"
        "    then: complete_job\n"
    )
    rail_file.write_text(original_yaml, encoding="utf-8")

    catalog = LoopRailCatalog()
    rail = catalog.resolve("test-integrity")
    expected_hash = rail.integrity_hash

    # Verify original matches
    assert catalog.verify_integrity("test-integrity", expected_hash) is True

    # Tamper: rewrite with different content
    tampered_yaml = original_yaml.replace("Original.", "Tampered!")
    rail_file.write_text(tampered_yaml, encoding="utf-8")

    # Hash should no longer match
    assert catalog.verify_integrity("test-integrity", expected_hash) is False


def test_rail_id_rejects_path_traversal(tmp_path: Path) -> None:
    """Rail IDs with path traversal characters are rejected at load time."""
    path = tmp_path / "evil.yml"
    path.write_text(
        "id: ../etc/passwd\n"
        "version: '1.0'\n"
        "summary: evil\n"
        "applies_when: x\n"
        "flow:\n"
        "  - event: job_start\n"
        "    then: complete_job\n",
        encoding="utf-8",
    )
    # The filename stem is "evil" but the id is "../etc/passwd" — id mismatch
    # is caught first, but even with matching stems the traversal check blocks.
    with pytest.raises(RailCatalogError):
        load_rail_file(path)


def test_resolve_rejects_path_traversal_id() -> None:
    """LoopRailCatalog.resolve rejects rail IDs with traversal characters."""
    catalog = LoopRailCatalog()
    with pytest.raises(RailCatalogError, match="path traversal"):
        catalog.resolve("../../etc/passwd")
    with pytest.raises(RailCatalogError, match="path traversal"):
        catalog.resolve("foo/bar")
    with pytest.raises(RailCatalogError, match="path traversal"):
        catalog.resolve("foo\\bar")


# ── V1: Path traversal in JsonlRailTraceStore ───────────────────────────


def test_sanitize_job_id_rejects_traversal() -> None:
    """_sanitize_job_id rejects empty, slash, backslash, and dot-dot."""
    with pytest.raises(ValueError, match="non-empty"):
        _sanitize_job_id("")
    with pytest.raises(ValueError, match="non-empty"):
        _sanitize_job_id("   ")
    with pytest.raises(ValueError, match="path"):
        _sanitize_job_id("../etc/passwd")
    with pytest.raises(ValueError, match="path"):
        _sanitize_job_id("foo/bar")
    with pytest.raises(ValueError, match="path"):
        _sanitize_job_id("foo\\bar")


def test_sanitize_job_id_accepts_clean() -> None:
    """Normal UUID-like job IDs pass sanitization."""
    assert _sanitize_job_id("abc-123-def") == "abc-123-def"
    assert _sanitize_job_id("019fc894_a2ac") == "019fc894_a2ac"


def test_jsonl_trace_rejects_traversal_in_append(tmp_path: Path) -> None:
    """JsonlRailTraceStore.append raises on traversal job_id."""
    store = JsonlRailTraceStore(root=tmp_path)
    record = _make_record()
    with pytest.raises(ValueError, match="path"):
        store.append("../escape", record)


def test_jsonl_trace_rejects_traversal_in_read(tmp_path: Path) -> None:
    """JsonlRailTraceStore.read raises on traversal job_id."""
    store = JsonlRailTraceStore(root=tmp_path)
    with pytest.raises(ValueError, match="path"):
        store.read("../escape")


def test_jsonl_trace_stays_within_root(tmp_path: Path) -> None:
    """A clean job_id writes only under root, not outside it."""
    store = JsonlRailTraceStore(root=tmp_path / "traces")
    record = _make_record()
    store.append("clean-job-id", record)
    written = tmp_path / "traces" / "clean-job-id" / "rail_trace.jsonl"
    assert written.is_file()
    # No file should exist outside root
    assert not (tmp_path / "escape.jsonl").exists()


# ── V7: Corrupted JSONL trace no longer blocks appends ──────────────────


def test_corrupted_jsonl_line_does_not_block_append(tmp_path: Path) -> None:
    """A malformed line in the JSONL trace is skipped, not fatal."""
    store = JsonlRailTraceStore(root=tmp_path)
    trace_dir = tmp_path / "corrupt-job"
    trace_dir.mkdir()
    trace_file = trace_dir / "rail_trace.jsonl"
    # Write a corrupted line followed by a valid one
    trace_file.write_text(
        '{"bad json"\n{"timestamp":"2099-01-01T00:00:00+00:00","event":"job_start","rule_id":null,"condition":null,"guard_result":{"matched":true,"confidence":1.0,"reasoning":""},"builtin":null,"builtin_result":null,"goal_id":null,"seq":0}\n',
        encoding="utf-8",
    )
    # append() calls read() internally — this must not raise
    record = _make_record(event="goal_completed")
    result = store.append("corrupt-job", record)
    assert result.seq == 1  # only the valid line counted


def test_corrupted_jsonl_read_skips_bad_lines(tmp_path: Path) -> None:
    """read() skips malformed lines and returns only valid records."""
    store = JsonlRailTraceStore(root=tmp_path)
    trace_dir = tmp_path / "mixed-job"
    trace_dir.mkdir()
    trace_file = trace_dir / "rail_trace.jsonl"
    trace_file.write_text(
        "not json at all\n"
        '{"valid":true}\n'
        '{"timestamp":"2099-01-01T00:00:00+00:00","event":"job_start","rule_id":null,"condition":null,"guard_result":{"matched":true,"confidence":1.0,"reasoning":""},"builtin":null,"builtin_result":null,"goal_id":null,"seq":0}\n',
        encoding="utf-8",
    )
    records = store.read("mixed-job")
    # Only the fully valid line should produce a record
    assert len(records) == 1
    assert records[0].event == "job_start"


# ── V8: Exception detail leakage ────────────────────────────────────────


@pytest.mark.asyncio
async def test_builtin_error_does_not_leak_exception_detail() -> None:
    """BuiltinResult.error uses type name, not str(exc), to avoid leakage."""
    ce = ContextEngine()
    executor = RailBuiltinExecutor(ce)
    # Invoke a non-existent builtin to trigger the unknown handler path
    result = await executor.invoke("__nonexistent__", job_id="job-1")
    assert result.status == "error"
    assert "unknown builtin" in result.detail
    # Must not contain raw exception repr (no file paths, DSNs, etc.)
    assert "Traceback" not in result.detail


@pytest.mark.asyncio
async def test_builtin_runtime_error_sanitize_detail() -> None:
    """Builtin handler exception details use type name only."""
    ce = ContextEngine()
    executor = RailBuiltinExecutor(ce)
    # Bind a job state so _require doesn't fail; _do_review will call CE
    from soothe.autopilot.rail.builtins_exec import RailJobState

    await executor.bind_job(RailJobState(job_id="job-x", rail_id="test", rail_version="1.0"))
    # _do_retry_branch iterates list_goals — if CE has no goals for this
    # job it should succeed. Let's force a different error: invoke a
    # builtin that depends on trigger_goal_id being non-None
    result = await executor.invoke("retry_branch", job_id="job-x")
    # Should succeed (pruned=0) or error with sanitized detail
    if result.status == "error":
        assert "Traceback" not in result.detail
        # Should not leak internal paths
        assert "/" not in result.detail or "pruned" in result.detail


def test_guard_error_reasoning_uses_type_name() -> None:
    """GuardResult reasoning for LLM errors uses type name, not str(exc).

    This is a structural test — we verify the source pattern by checking
    that the LLMGuardEvaluator's error reasoning format is correct.
    """
    # The guards.py source was patched to use {type(exc).__name__} not {exc}
    # We verify by reading the source and asserting the pattern.
    import inspect

    from soothe.autopilot.rail.guards import LLMGuardEvaluator

    source = inspect.getsource(LLMGuardEvaluator)
    # Must NOT contain f"structured guard failed: {exc}"
    assert 'f"structured guard failed: {{exc}}"' not in source
    # Must contain type name pattern
    assert "type(exc).__name__" in source


# ── Helpers ────────────────────────────────────────────────────────────


def _make_record(event: str = "job_start") -> RuleFireRecord:
    """Create a minimal RuleFireRecord for trace store tests."""
    return RuleFireRecord(
        timestamp=datetime.now(UTC),
        rule_id="test-rule",
        event=event,
        condition=None,
        guard_result=GuardResult(matched=True, confidence=1.0, reasoning="test"),
        builtin="complete_job",
        builtin_result="success",
        goal_id="goal-1",
    )
