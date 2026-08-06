"""Build worker contribution / wire response from a completed PlanResult.

StrangeLoop Plan-Execute-Eval owns goal-done judgment. Autopilot consensus
compares goal text to the wire response synthesized here — not host workspace
probes (IG-710 / RFC-204).
"""

from __future__ import annotations

import hashlib
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from soothe.autopilot.dispatch.models import FileTouchSummary

# Path-like tokens in evidence / action text (any name.ext; not a latch probe).
_PATH_TOKEN = re.compile(
    r"(?:/(?:[\w.-]+/)*[\w.-]+\.\w{1,16}"
    r"|(?:[\w.-]+/)+[\w.-]+\.\w{1,16}"
    r"|(?<![\w/])[\w.-]+\.\w{1,16}(?![\w.]))"
)


def decision_step_actions(decision: Any | None) -> list[Any]:
    """Return plan step actions from an ``AgentDecision``-like object.

    Prefer ``steps`` (canonical ``AgentDecision`` field). Accept legacy
    ``actions`` only for older fixtures / wire payloads.
    """
    if decision is None:
        return []
    steps = getattr(decision, "steps", None)
    if isinstance(steps, list) and steps:
        return list(steps)
    actions = getattr(decision, "actions", None)
    if isinstance(actions, list) and actions:
        return list(actions)
    return []


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
    for action in decision_step_actions(decision)[:40]:
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


def synthesize_sloop_response(plan_result: Any | None) -> str:
    """Derive the StrangeLoop response string for the consensus wire field.

    Prefer explicit ``evidence_summary``, then user-visible ``full_output``,
    then completed decision step descriptions. Never uses the goal text.
    """
    if plan_result is None:
        return ""

    summary = (getattr(plan_result, "evidence_summary", None) or "").strip()
    if summary:
        return summary[:2048]

    full_output = (getattr(plan_result, "full_output", None) or "").strip()
    if full_output:
        return full_output[:2048]

    decision = getattr(plan_result, "decision", None)
    actions = decision_step_actions(decision)
    if actions:
        bits: list[str] = []
        for action in actions[:10]:
            if isinstance(action, dict):
                text = str(action.get("description", "") or "").strip()
            else:
                text = str(getattr(action, "description", "") or "").strip()
            if text:
                bits.append(text[:200])
        if bits:
            return "Completed steps: " + "; ".join(bits)

    return ""
