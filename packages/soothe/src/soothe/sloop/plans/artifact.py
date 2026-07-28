"""Workspace plan artifact helpers (RFC-633 / IG-658)."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path

_SLUG_RE = re.compile(r"[^a-z0-9]+")
_FRONTMATTER_RE = re.compile(r"\A---\n(.*?)\n---\n?", re.DOTALL)


def slugify_plan_name(text: str, *, max_len: int = 48) -> str:
    """Return a filesystem-safe slug from a goal or plan title."""
    raw = (text or "").strip().lower()
    # Prefer first markdown heading if present.
    for line in raw.splitlines():
        s = line.strip()
        if s.startswith("#"):
            raw = s.lstrip("#").strip().lower()
            break
    slug = _SLUG_RE.sub("-", raw).strip("-")
    if not slug:
        slug = "plan"
    return slug[:max_len].rstrip("-") or "plan"


def plan_artifact_path(workspace: str | Path, *, title: str, when: datetime | None = None) -> Path:
    """Build `{workspace}/.soothe/plans/{timestamp}-{slug}.md`."""
    ts = (when or datetime.now(UTC)).strftime("%Y%m%dT%H%M%SZ")
    slug = slugify_plan_name(title)
    return Path(workspace) / ".soothe" / "plans" / f"{ts}-{slug}.md"


def _render_frontmatter(
    *,
    status: str,
    goal_id: str,
    loop_id: str,
    created_at: str,
) -> str:
    return (
        "---\n"
        f"status: {status}\n"
        f"goal_id: {goal_id or ''}\n"
        f"loop_id: {loop_id or ''}\n"
        f"created_at: {created_at}\n"
        "---\n\n"
    )


def write_plan_artifact(
    workspace: str | Path,
    plan_markdown: str,
    *,
    title: str,
    goal_id: str = "",
    loop_id: str = "",
    status: str = "draft",
) -> Path:
    """Write a new plan markdown file under ``.soothe/plans/``.

    Args:
        workspace: Loop workspace root.
        plan_markdown: Plan body (frontmatter stripped if already present).
        title: Used for the filename slug.
        goal_id: Optional goal id for frontmatter.
        loop_id: Optional loop/thread id for frontmatter.
        status: ``draft`` | ``approved`` | ``rejected``.

    Returns:
        Absolute path to the written file.
    """
    path = plan_artifact_path(workspace, title=title)
    path.parent.mkdir(parents=True, exist_ok=True)
    body = (plan_markdown or "").strip()
    if body.startswith("---"):
        m = _FRONTMATTER_RE.match(body)
        if m:
            body = body[m.end() :].lstrip()
    created = datetime.now(UTC).isoformat()
    text = _render_frontmatter(
        status=status,
        goal_id=goal_id,
        loop_id=loop_id,
        created_at=created,
    ) + (body + ("\n" if body and not body.endswith("\n") else ""))
    path.write_text(text, encoding="utf-8")
    return path.resolve()


def update_plan_artifact_status(path: str | Path, status: str) -> None:
    """Update ``status`` in YAML frontmatter when present; otherwise no-op prepend."""
    p = Path(path)
    if not p.is_file():
        return
    raw = p.read_text(encoding="utf-8")
    m = _FRONTMATTER_RE.match(raw)
    if not m:
        created = datetime.now(UTC).isoformat()
        p.write_text(
            _render_frontmatter(status=status, goal_id="", loop_id="", created_at=created) + raw,
            encoding="utf-8",
        )
        return
    fm = m.group(1)
    if re.search(r"(?m)^status:\s*", fm):
        fm = re.sub(r"(?m)^status:\s*.*$", f"status: {status}", fm, count=1)
    else:
        fm = f"status: {status}\n{fm}"
    body = raw[m.end() :]
    p.write_text(f"---\n{fm}\n---\n{body}", encoding="utf-8")


def parse_planner_subagent_review_answers(
    answers: tuple[str, ...] | list[str],
) -> tuple[str, str]:
    """Parse planner-subagent review answers into ``(action, comments)``.

    Actions: ``approve`` | ``reject`` | ``comments``.

    Expects the plan-review widget (or equivalent) to send action label in
    answers[0] and optional revision text in answers[1].
    """
    vals = [str(a or "").strip() for a in answers]
    q1 = vals[0] if vals else ""
    q2 = vals[1] if len(vals) > 1 else ""
    low = q1.lower()
    if low.startswith("approve"):
        return "approve", q2
    if low.startswith("reject"):
        return "reject", q2
    if low.startswith("more") or low in {"comments", "comment", "c"}:
        return "comments", q2
    # Untagged free-text body (single answer) → revise with comments.
    return "comments", q2 or q1
