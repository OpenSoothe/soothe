"""Fast grep via The Silver Searcher (``ag``) with Python fallback."""

from __future__ import annotations

import logging
import re
import shutil
import subprocess
from pathlib import Path

from .protocol import GrepMatch, GrepResult

logger = logging.getLogger(__name__)

_AG_GREP_TIMEOUT_S = 120
_ag_available: bool | None = None


def is_ag_available() -> bool:
    """Return whether ``ag`` is on PATH (cached after first check)."""
    global _ag_available
    if _ag_available is None:
        _ag_available = shutil.which("ag") is not None
    return _ag_available


def reset_ag_availability_cache() -> None:
    """Clear cached ``ag`` availability (for tests)."""
    global _ag_available
    _ag_available = None


def grep_with_ag(
    *,
    workspace: Path,
    search_path: Path,
    pattern: str,
    glob: str | None,
    output_mode: str,
    timeout_s: float = _AG_GREP_TIMEOUT_S,
) -> GrepResult | list[str] | str | None:
    """Run ``ag`` when available.

    Returns:
        Parsed grep output, or ``None`` when ``ag`` is unavailable or fails.
    """
    ag_bin = shutil.which("ag")
    if not ag_bin:
        return None

    cmd = [ag_bin, "--nocolor", "--noheading"]
    if output_mode == "files_with_matches":
        cmd.append("-l")
    elif output_mode == "count":
        cmd.append("--stats")
    else:
        cmd.extend(["-n", "--column"])

    if glob:
        cmd.extend(["--glob", glob])

    cmd.extend([pattern, str(search_path)])

    try:
        completed = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout_s,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        logger.warning("ag grep failed (%s); falling back to Python walk", exc)
        return None

    if completed.returncode not in (0, 1):
        logger.warning(
            "ag grep exited %s: %s; falling back to Python walk",
            completed.returncode,
            (completed.stderr or completed.stdout or "").strip()[:200],
        )
        return None

    stdout = completed.stdout or ""
    if output_mode == "files_with_matches":
        files = [
            _to_workspace_relative(workspace, line.strip())
            for line in stdout.splitlines()
            if line.strip()
        ]
        return files

    if output_mode == "count":
        total = _parse_ag_stats_match_count(stdout)
        if total is None:
            return None
        return str(total)

    matches = _parse_ag_content_lines(workspace, stdout, pattern)
    return GrepResult(
        matches=matches,
        files_searched=len({m.path for m in matches}),
        total_matches=len(matches),
    )


def _parse_ag_stats_match_count(stdout: str) -> int | None:
    """Parse ``ag --stats`` output for total match count."""
    for line in stdout.splitlines():
        stripped = line.strip()
        if stripped.startswith("matches found:"):
            try:
                return int(stripped.split(":", 1)[1].strip())
            except ValueError:
                return None
    return 0


def _parse_ag_content_lines(
    workspace: Path,
    stdout: str,
    pattern: str,
) -> list[GrepMatch]:
    """Parse ``ag -n --column`` lines into ``GrepMatch`` rows."""
    matches: list[GrepMatch] = []
    for line in stdout.splitlines():
        if not line.strip():
            continue
        parsed = _parse_ag_match_line(line)
        if parsed is None:
            continue
        file_path, line_number, line_content = parsed
        rel_path = _to_workspace_relative(workspace, file_path)
        match_start, match_end = _match_span(line_content, pattern)
        matches.append(
            GrepMatch(
                path=rel_path,
                line_number=line_number,
                line_content=line_content,
                match_start=match_start,
                match_end=match_end,
            )
        )
    return matches


def _parse_ag_match_line(line: str) -> tuple[str, int, str] | None:
    """Parse ``path:line:column:content`` or ``path:line:content``."""
    parts = line.split(":", 3)
    if len(parts) < 3:
        return None
    file_path = parts[0]
    try:
        line_number = int(parts[1])
    except ValueError:
        return None
    if len(parts) == 4:
        line_content = parts[3]
    else:
        line_content = parts[2]
    return file_path, line_number, line_content


def _match_span(line_content: str, pattern: str) -> tuple[int, int]:
    """Best-effort match span for a regex pattern within a line."""
    try:
        found = re.search(pattern, line_content)
    except re.error:
        found = None
    if found:
        return found.start(), found.end()
    return 0, len(line_content)


def _to_workspace_relative(workspace: Path, file_path: str) -> str:
    """Normalize ``ag`` output paths to workspace-relative strings."""
    path = Path(file_path)
    if not path.is_absolute():
        return str(path)
    try:
        return str(path.resolve().relative_to(workspace.resolve()))
    except ValueError:
        return str(path)
