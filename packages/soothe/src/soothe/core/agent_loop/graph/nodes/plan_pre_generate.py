"""Bounded pre-generate evidence probe node (RFC-220 split plan flow)."""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

from ..runtime_context import LoopRuntimeContext

logger = logging.getLogger(__name__)


def _extract_goal_path_hint(goal: str) -> str | None:
    """Extract a likely workspace-relative path hint from goal text."""
    fenced = re.findall(r"`([^`]+)`", goal)
    candidates = fenced + re.findall(r"([A-Za-z0-9_./-]+\.[A-Za-z0-9_]+)", goal)
    for raw in candidates:
        hint = raw.strip().strip(".,:;")
        if "/" in hint or "." in hint:
            return hint
    return None


def _read_preview(path: Path, *, max_lines: int = 40) -> str:
    """Read a bounded text preview for evidence summary."""
    text = path.read_text(encoding="utf-8", errors="ignore")
    lines = text.splitlines()
    preview = "\n".join(lines[:max_lines]).strip()
    return preview if preview else "<empty file>"


async def node_plan_pre_generate(ctx: LoopRuntimeContext, _state: dict[str, Any]) -> dict[str, Any]:
    """Collect up to three deterministic readonly evidence probes for generate phase."""
    state = ctx.loop_state
    cfg = ctx.agent_loop.config.agentic
    max_uses = max(1, int(getattr(cfg, "plan_pre_generate_probe_max_uses", 3)))

    evidence_lines: list[str] = []
    uses = 0
    root = Path(state.workspace).expanduser() if state.workspace else None

    if root is None or not root.exists():
        evidence_lines.append("Workspace path unavailable; generate should begin with discovery.")
        ctx.scratch.pre_generate_evidence = evidence_lines
        await ctx.emit(
            "planning",
            {
                "iteration": state.iteration,
                "phase": "plan_pre_generate",
                "tool_uses": uses,
                "evidence_count": len(evidence_lines),
            },
        )
        return {}

    if uses < max_uses:
        entries = sorted(p.name for p in root.iterdir())[:24]
        evidence_lines.append(f"workspace_root: {', '.join(entries)}")
        uses += 1

    if uses < max_uses:
        anchor = root / "README.md"
        if not anchor.exists():
            anchor = root / "pyproject.toml"
        if anchor.exists() and anchor.is_file():
            evidence_lines.append(f"{anchor.name}: {_read_preview(anchor)}")
        else:
            evidence_lines.append("anchor_file: README.md/pyproject.toml not found")
        uses += 1

    if uses < max_uses:
        hint = _extract_goal_path_hint(state.goal)
        if hint:
            hinted_path = (root / hint).resolve()
            try:
                hinted_path.relative_to(root.resolve())
            except ValueError:
                hinted_path = root / hint
            if hinted_path.exists() and hinted_path.is_file():
                evidence_lines.append(
                    f"goal_hint {hint}: {_read_preview(hinted_path, max_lines=24)}"
                )
            elif hinted_path.exists() and hinted_path.is_dir():
                sub = sorted(p.name for p in hinted_path.iterdir())[:20]
                evidence_lines.append(f"goal_hint_dir {hint}: {', '.join(sub)}")
            else:
                evidence_lines.append(f"goal_hint {hint}: not found")
        else:
            evidence_lines.append("goal_hint: none inferred from goal text")
        uses += 1

    if len(evidence_lines) > max_uses:
        evidence_lines = evidence_lines[:max_uses]
    ctx.scratch.pre_generate_evidence = evidence_lines

    await ctx.emit(
        "planning",
        {
            "iteration": state.iteration,
            "phase": "plan_pre_generate",
            "tool_uses": uses,
            "evidence_count": len(evidence_lines),
        },
    )
    logger.debug("[plan_pre_generate] iter=%d probe_uses=%d", state.iteration, uses)
    return {}
