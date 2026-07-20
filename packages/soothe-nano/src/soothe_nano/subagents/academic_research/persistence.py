"""Persist academic_research reports under workspace ``.soothe/agents/academic_research/``."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from soothe_nano.utils.runtime import get_workspace_subagent_output_dir

from .display_summary import academic_research_brief_summary_for_display, derive_report_title

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SavedAcademicResearchReport:
    """Result of persisting a synthesized literature report."""

    host_path: Path
    display_path: str
    brief_summary: str


def slugify_report_title(title: str, *, max_len: int = 60) -> str:
    """Convert a title into a filesystem-safe slug."""
    slug = re.sub(r"[^\w\s-]", "", (title or "").lower())
    slug = re.sub(r"[\s_]+", "-", slug).strip("-")
    if not slug:
        slug = "academic-report"
    return slug[:max_len].strip("-") or "academic-report"


def _display_path_for(host_path: Path) -> str:
    """Return a workspace-relative path when possible."""
    from soothe_nano.workspace.workspace_runtime import get_workspace_context

    ctx = get_workspace_context()
    if ctx.workspace is not None:
        try:
            return host_path.resolve().relative_to(ctx.workspace.resolve()).as_posix()
        except ValueError:
            pass
    return host_path.as_posix()


def _unique_report_path(reports_dir: Path, slug: str) -> Path:
    """Allocate a non-colliding report filename using UTC timestamp."""
    ts = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    return reports_dir / f"{slug}_{ts}.md"


def save_academic_research_report(
    report: str,
    *,
    topic: str,
    soothe_config: object | None = None,
) -> SavedAcademicResearchReport | None:
    """Write the full report markdown and return paths plus a brief summary."""
    text = (report or "").strip()
    if not text:
        return None

    slug = slugify_report_title(derive_report_title(text, topic))
    reports_dir = get_workspace_subagent_output_dir("academic_research")
    host_path = _unique_report_path(reports_dir, slug)

    try:
        from soothe_nano.toolkits._internal.backend_ops import backend_mkdir, backend_write_file

        backend_mkdir(reports_dir, soothe_config)
        backend_write_file(host_path, text, soothe_config)
    except Exception:
        logger.warning("[academic_research] failed to save report", exc_info=True)
        return None

    brief_summary = academic_research_brief_summary_for_display(text)
    display_path = _display_path_for(host_path)
    logger.info("[academic_research] saved report to %s", display_path)
    return SavedAcademicResearchReport(
        host_path=host_path,
        display_path=display_path,
        brief_summary=brief_summary,
    )


def format_saved_report_answer(saved: SavedAcademicResearchReport) -> str:
    """Format the subagent result as summary plus pointer to the saved file."""
    return f"## Summary\n\n{saved.brief_summary}\n\nFull report saved to: `{saved.display_path}`"


__all__ = [
    "SavedAcademicResearchReport",
    "format_saved_report_answer",
    "save_academic_research_report",
    "slugify_report_title",
]
