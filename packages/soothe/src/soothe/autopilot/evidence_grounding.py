"""Consensus / health evidence helpers (IG-680).

Structural workspace probes and path extraction from execution evidence —
not content-judgment keyword heuristics (RFC-630).
"""

from __future__ import annotations

import hashlib
import logging
import re
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from soothe.autopilot.engine_models import FileTouchSummary

logger = logging.getLogger(__name__)

# Deliverable markers used only as structural presence probes (paths exist + non-empty).
_DELIVERABLE_MARKERS: tuple[str, ...] = (
    "SUMMARY.md",
    "VERIFY.md",
    "docs/DESIGN.md",
    "pyproject.toml",
)

# Path-like tokens in evidence / action text (extensions constrain false positives).
_PATH_TOKEN = re.compile(
    r"(?:/(?:[\w.-]+/)*[\w.-]+\.\w{1,10}"
    r"|(?:[\w.-]+/)+[\w.-]+\.(?:py|md|toml|yml|yaml|json|txt|cfg|ini))"
)


def normalize_goal_description(description: str) -> str:
    """Normalize a goal description for dedupe under a parent."""
    return " ".join((description or "").strip().lower().split())


def workspace_deliverable_probe(workspace: str | None) -> str:
    """Return a short grounded evidence string from workspace artifacts, or empty."""
    if not workspace or not str(workspace).strip():
        return ""
    root = Path(workspace).expanduser()
    if not root.is_dir():
        return ""

    hits: list[str] = []
    for rel in _DELIVERABLE_MARKERS:
        path = root / rel
        try:
            if path.is_file() and path.stat().st_size > 0:
                hits.append(f"{rel} present ({path.stat().st_size} bytes)")
        except OSError:
            continue

    tests_dir = root / "tests"
    if tests_dir.is_dir():
        try:
            n = sum(1 for p in tests_dir.rglob("test_*.py") if p.is_file())
            if n:
                hits.append(f"tests/: {n} test_*.py files")
        except OSError:
            pass

    if not hits:
        return ""
    return "Workspace artifact probe:\n- " + "\n- ".join(hits)


def workspace_has_deliverables(workspace: str | None) -> bool:
    """True when structural deliverable markers exist under workspace."""
    return bool(workspace_deliverable_probe(workspace))


def workspace_pytest_probe(workspace: str | None, *, timeout_s: float = 60.0) -> str:
    """Run ``python -m pytest -q`` when ``pyproject.toml`` + ``tests/`` exist.

    Structural success-criteria check for TASK.md-style deliverables — not
    content judgment. Returns a one-line result or empty string on skip/error.
    """
    if not workspace or not str(workspace).strip():
        return ""
    root = Path(workspace).expanduser()
    if not root.is_dir():
        return ""
    if not (root / "pyproject.toml").is_file():
        return ""
    tests_dir = root / "tests"
    if not tests_dir.is_dir():
        return ""
    try:
        proc = subprocess.run(
            ["python", "-m", "pytest", "-q", "--tb=no"],
            cwd=str(root),
            capture_output=True,
            text=True,
            timeout=timeout_s,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        logger.debug("pytest probe skipped for %s: %s", root, exc)
        return ""
    tail = (proc.stdout or proc.stderr or "").strip().splitlines()
    summary = tail[-1] if tail else f"exit={proc.returncode}"
    status = "PASS" if proc.returncode == 0 else "FAIL"
    return f"pytest -q: {status} ({summary})"


def enrich_workspace_evidence(workspace: str | None) -> str:
    """Combine artifact markers + optional pytest probe for consensus grounding."""
    parts: list[str] = []
    probe = workspace_deliverable_probe(workspace)
    if probe:
        parts.append(probe)
    pytest_line = workspace_pytest_probe(workspace)
    if pytest_line:
        parts.append(pytest_line)
    return "\n".join(parts).strip()


def extract_path_tokens(*texts: str) -> list[str]:
    """Extract path-like tokens from evidence / action strings."""
    found: list[str] = []
    seen: set[str] = set()
    for text in texts:
        if not text:
            continue
        for match in _PATH_TOKEN.findall(text):
            if match not in seen:
                seen.add(match)
                found.append(match)
    return found


def build_files_touched(
    *,
    goal_id: str,
    workspace: str | None,
    evidence_summary: str,
    plan_result: Any | None,
) -> dict[str, FileTouchSummary]:
    """Best-effort files_touched map from PlanResult + evidence text.

    Hashes files that exist on disk (under workspace when relative). Caps at 50.
    """
    texts: list[str] = [evidence_summary or ""]
    decision = getattr(plan_result, "decision", None) if plan_result is not None else None
    actions = getattr(decision, "actions", None) if decision is not None else None
    if isinstance(actions, list):
        for action in actions[:40]:
            if isinstance(action, dict):
                texts.append(str(action.get("description", "")))
            else:
                texts.append(str(getattr(action, "description", action) or ""))

    root = Path(workspace).expanduser() if workspace else None
    out: dict[str, FileTouchSummary] = {}
    for token in extract_path_tokens(*texts):
        if len(out) >= 50:
            break
        path = Path(token)
        if not path.is_absolute() and root is not None:
            path = root / token
        try:
            if not path.is_file():
                continue
            digest = hashlib.sha256(path.read_bytes()).hexdigest()[:16]
        except OSError:
            continue
        key = str(path)
        out[key] = FileTouchSummary(
            content_hash=digest,
            last_op="write",
            goal_id_origin=goal_id,
            last_touched_at=datetime.now(UTC),
        )
    return out


def format_contribution_evidence(
    *,
    evidence_summary: str,
    files_touched: dict[str, FileTouchSummary] | None,
    findings: list[Any] | None,
) -> str:
    """Build grounded consensus evidence text (never the bare goal description)."""
    parts: list[str] = []
    summary = (evidence_summary or "").strip()
    if summary:
        parts.append(summary)
    if files_touched:
        names = sorted(files_touched)[:20]
        parts.append("files_touched: " + ", ".join(names))
    if findings:
        for finding in findings[:10]:
            text = getattr(finding, "summary", None) or str(finding)
            text = str(text).strip()
            if text:
                parts.append(f"finding: {text[:500]}")
    return "\n".join(parts).strip()
