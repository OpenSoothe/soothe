"""Unit tests for the decompose_task grounding guard (d15f hallucination defense)."""

from __future__ import annotations

from soothe.context.decomposition import DecompositionProposal, ProposedSubtask
from soothe.sloop.decompose.grounding_guard import (
    build_no_evidence_guidance,
    build_unconfirmed_paths_guidance,
    extract_cited_paths,
    find_unconfirmed_paths,
)

# ── extract_cited_paths ────────────────────────────────────────────────────


def test_extract_paths_from_description() -> None:
    paths = extract_cited_paths("Enhance Swift client (client/swift/) and Go")
    assert "client/swift/" in paths
    # Plain word "Swift" without a slash is not a path.
    assert "Swift" not in paths


def test_extract_paths_from_full_description() -> None:
    text = (
        "Review and enhance packages/client-go/src/goosews/.\n"
        "CURRENT STATE:\n- goosews.go: WebSocket connection\n"
        "Also see client/python/transport.py"
    )
    paths = extract_cited_paths(text)
    assert "packages/client-go/src/goosews/" in paths
    assert "client/python/transport.py" in paths


def test_extract_paths_dedupes() -> None:
    text = "work on client/swift/ and client/swift/ again"
    paths = extract_cited_paths(text)
    assert paths.count("client/swift/") == 1


def test_extract_paths_ignores_prose_slash_words() -> None:
    paths = extract_cited_paths("add/delete files, read/write content, review/polish")
    assert paths == []


def test_extract_paths_empty_text() -> None:
    assert extract_cited_paths("") == []
    assert extract_cited_paths(None) == []  # type: ignore[arg-type]


def test_extract_paths_file_with_extension() -> None:
    paths = extract_cited_paths("edit src/foo.py and tests/bar_test.go")
    assert "src/foo.py" in paths
    assert "tests/bar_test.go" in paths


# ── find_unconfirmed_paths ─────────────────────────────────────────────────


def _proposal(*descs: str) -> DecompositionProposal:
    return DecompositionProposal(
        parent_step_id="INF-01",
        subtasks=[ProposedSubtask(description=d, full_description=d) for d in descs],
    )


def test_find_unconfirmed_paths_detects_missing(tmp_path) -> None:
    (tmp_path / "client" / "go").mkdir(parents=True)
    proposal = _proposal("Enhance Go (client/go/)", "Enhance Swift (client/swift/)")
    missing = find_unconfirmed_paths(proposal, workspace=str(tmp_path))
    assert "client/swift/" in missing
    assert "client/go/" not in missing


def test_find_unconfirmed_paths_empty_when_all_exist(tmp_path) -> None:
    (tmp_path / "client" / "go").mkdir(parents=True)
    (tmp_path / "client" / "swift").mkdir(parents=True)
    proposal = _proposal("Enhance Go (client/go/)", "Enhance Swift (client/swift/)")
    assert find_unconfirmed_paths(proposal, workspace=str(tmp_path)) == []


def test_find_unconfirmed_paths_no_cited_paths() -> None:
    proposal = _proposal("do A thoroughly", "finish B")
    assert find_unconfirmed_paths(proposal, workspace="/tmp") == []


def test_find_unconfirmed_paths_fails_open_when_workspace_none() -> None:
    """No workspace → guard skipped (fail open), returns no missing paths."""
    proposal = _proposal("Enhance Swift (client/swift/)")
    assert find_unconfirmed_paths(proposal, workspace=None) == []


def test_find_unconfirmed_paths_fails_open_when_workspace_empty() -> None:
    """Empty workspace string → guard skipped (fail open)."""
    proposal = _proposal("Enhance Swift (client/swift/)")
    assert find_unconfirmed_paths(proposal, workspace="") == []


# ── guidance builders ──────────────────────────────────────────────────────


def test_build_no_evidence_guidance() -> None:
    msg = build_no_evidence_guidance(step_id="INF-01")
    assert "INF-01" in msg
    assert "NOT queued" in msg
    assert "evidence" in msg.lower()


def test_build_unconfirmed_paths_guidance() -> None:
    msg = build_unconfirmed_paths_guidance(["client/swift/", "client/kotlin/"], step_id="INF-01")
    assert "INF-01" in msg
    assert "client/swift/" in msg
    assert "NOT queued" in msg
