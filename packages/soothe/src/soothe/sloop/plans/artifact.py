"""Workspace plan artifact helpers (RFC-633)."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path

_SLUG_RE = re.compile(r"[^a-z0-9]+")
_FRONTMATTER_RE = re.compile(r"\A---\n(.*?)\n---\n?", re.DOTALL)

# Matches a section heading (``### Title``) whose body is a bare placeholder
# like ``None``, ``None.``, ``N/A``, ``- None``, or ``—``. The heading + body
# block is removed so the plan stays compact.
_NONE_SECTION_RE = re.compile(
    r"\n?^#{2,3}\s+[^\n]+\n"  # heading line (## or ###) + newline
    r"(?:[\s-]*"  # optional whitespace / bullet dashes before placeholder
    r"(?:None|N/?A|—|--|n/a)"  # placeholder variants
    r"[.\s]*"  # optional trailing punctuation/whitespace
    r")\s*\n",
    re.MULTILINE | re.IGNORECASE,
)


def strip_empty_plan_sections(markdown: str) -> str:
    """Remove plan sections whose body is a bare ``None`` / ``N/A`` placeholder.

    The plan templates instruct the LLM to OMIT inapplicable optional sections
    entirely, but models sometimes emit a literal ``None`` or ``N/A`` as the
    section body. This post-processor strips those dead sections so the
    rendered plan stays compact and relevant.

    Only sections with a placeholder body are removed; sections with real
    content (even short) are left untouched.
    """
    text = (markdown or "").strip()
    if not text:
        return text
    # Ensure a trailing newline so the regex can match the last section.
    text += "\n"
    # Repeat until stable — adjacent sections may collapse.
    prev: str | None = None
    while prev != text:
        prev = text
        text = _NONE_SECTION_RE.sub("\n", text)
    return text.strip()


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


def strip_plan_frontmatter(markdown: str) -> str:
    """Remove YAML frontmatter from a plan artifact for prompts / display."""
    raw = (markdown or "").strip()
    if not raw.startswith("---"):
        return raw
    m = _FRONTMATTER_RE.match(raw)
    if not m:
        return raw
    return raw[m.end() :].lstrip()


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


def parse_plan_review_answers(
    answers: tuple[str, ...] | list[str],
) -> tuple[str, str]:
    """Parse plan-review answers into ``(action, text)``.

    Actions: ``approve`` | ``reject`` | ``refine``.

    Expects the plan-review widget (or equivalent) to send the action label
    in answers[0] and optional refinement text in answers[1]. Free-text
    input that does not start with a known action is treated as
    a refinement carrying that text as feedback, so a typed
    refinement still works.
    """
    vals = [str(a or "").strip() for a in answers]
    q1 = vals[0] if vals else ""
    q2 = vals[1] if len(vals) > 1 else ""
    low = q1.lower()
    if low.startswith("approve"):
        return "approve", q2
    if low.startswith("reject"):
        return "reject", q2
    if low.startswith("refine"):
        return "refine", q2
    # Untagged free-text body (single answer) → refine with that text as
    # refinement feedback.
    return "refine", q2 or q1
