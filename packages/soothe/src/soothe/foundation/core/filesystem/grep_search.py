"""Fast grep via The Silver Searcher (``ag``) with Python fallback."""

from __future__ import annotations

import fnmatch
import logging
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from .protocol import GrepMatch, GrepResult

logger = logging.getLogger(__name__)

_AG_GREP_TIMEOUT_S = 120
_AG_ENV_VAR = "SOOTHE_AG_PATH"
# Well-known install locations when ``ag`` is not on the daemon's PATH.
_AG_COMMON_PATHS: tuple[str, ...] = (
    "/opt/homebrew/bin/ag",  # macOS Apple Silicon Homebrew
    "/usr/local/bin/ag",  # macOS Intel Homebrew / manual install
    "/usr/bin/ag",  # Linux distro packages
)
# Safe threshold for file count before hitting typical ulimit (256 on macOS).
# When directory exceeds this, skip ag proactively to avoid FD exhaustion.
_MAX_FD_SAFE_FILE_COUNT = 200
_ag_bin_cache: str | None = None
_ag_bin_resolved: bool = False


def get_ag_bin() -> str | None:
    """Return cached path to the ``ag`` binary, or ``None`` when unavailable."""
    global _ag_bin_cache, _ag_bin_resolved
    if not _ag_bin_resolved:
        _ag_bin_cache = _resolve_ag_bin()
        _ag_bin_resolved = True
    return _ag_bin_cache


def is_ag_available() -> bool:
    """Return whether ``ag`` is available (cached after first lookup)."""
    return get_ag_bin() is not None


def reset_ag_availability_cache() -> None:
    """Clear cached ``ag`` path (for tests)."""
    global _ag_bin_cache, _ag_bin_resolved
    _ag_bin_cache = None
    _ag_bin_resolved = False


def _resolve_ag_bin() -> str | None:
    """Resolve ``ag`` across hosts: env override, PATH, then common locations."""
    env_path = os.environ.get(_AG_ENV_VAR)
    if env_path:
        resolved = _normalize_ag_executable(env_path)
        if resolved is not None:
            return resolved
        logger.debug("%s is set but not an executable ag binary: %s", _AG_ENV_VAR, env_path)

    which_path = shutil.which("ag")
    if which_path:
        resolved = _normalize_ag_executable(which_path)
        if resolved is not None:
            return resolved

    for candidate in _AG_COMMON_PATHS:
        resolved = _normalize_ag_executable(candidate)
        if resolved is not None:
            logger.debug("Resolved ag via common path: %s", resolved)
            return resolved

    return None


def _normalize_ag_executable(path: str) -> str | None:
    """Return ``path`` when it points to an executable file."""
    candidate = Path(path).expanduser()
    if candidate.is_file() and os.access(candidate, os.X_OK):
        return str(candidate.resolve())
    return None


def _should_skip_ag_due_to_fd_limit(search_path: Path) -> bool:
    """Check if directory size might exceed system FD limit.

    Quick estimate of files in top 2 directory levels.
    When count exceeds safe threshold, skip ag proactively.

    Args:
        search_path: Directory to search.

    Returns:
        True if directory is too large for safe ag execution.
    """
    if not search_path.is_dir():
        return False

    try:
        count = 0
        # Quick estimate: count files in top 2 levels
        for item in search_path.iterdir():
            if item.is_file():
                count += 1
            elif item.is_dir():
                # Skip common ignore directories
                if item.name in {".git", "__pycache__", "node_modules", ".venv", "venv"}:
                    continue
                try:
                    for sub in item.iterdir():
                        if sub.is_file():
                            count += 1
                except OSError:
                    pass  # Can't read subdir, ignore
            if count > _MAX_FD_SAFE_FILE_COUNT:
                logger.debug(
                    "Directory %s has >%d files, skipping ag to avoid FD exhaustion",
                    search_path,
                    _MAX_FD_SAFE_FILE_COUNT,
                )
                return True
        return False
    except OSError:
        # Can't read directory, be conservative and skip ag
        return True


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
    ag_bin = get_ag_bin()
    if not ag_bin:
        return None

    # Pre-flight check: skip ag if directory is too large (FD exhaustion risk)
    if search_path.is_dir() and _should_skip_ag_due_to_fd_limit(search_path):
        return None  # Fallback to Python walk

    if output_mode == "files_with_matches":
        return _grep_with_ag_files(
            ag_bin=ag_bin,
            workspace=workspace,
            search_path=search_path,
            pattern=pattern,
            glob=glob,
            timeout_s=timeout_s,
        )

    if output_mode == "count":
        return _grep_with_ag_count(
            ag_bin=ag_bin,
            workspace=workspace,
            search_path=search_path,
            pattern=pattern,
            glob=glob,
            timeout_s=timeout_s,
        )

    if search_path.is_file():
        return _grep_with_ag_content_paths(
            ag_bin=ag_bin,
            workspace=workspace,
            pattern=pattern,
            glob=glob,
            timeout_s=timeout_s,
            paths=[search_path],
        )

    # Directory content search: ``ag -n`` on a tree root often returns nothing while
    # ``ag -l`` still finds files (observed on macOS ag 2.2). List matches first,
    # then fetch line content from those files only.
    files = _grep_with_ag_files(
        ag_bin=ag_bin,
        workspace=workspace,
        search_path=search_path,
        pattern=pattern,
        glob=glob,
        timeout_s=timeout_s,
    )
    if files is None:
        return None
    if not files:
        return GrepResult(matches=[], files_searched=0, total_matches=0)

    abs_paths = _resolve_ag_paths(workspace, files)
    if not abs_paths:
        return GrepResult(matches=[], files_searched=0, total_matches=0)

    return _grep_with_ag_content_paths(
        ag_bin=ag_bin,
        workspace=workspace,
        pattern=pattern,
        glob=glob,
        timeout_s=timeout_s,
        paths=abs_paths,
    )


def _grep_with_ag_files(
    *,
    ag_bin: str,
    workspace: Path,
    search_path: Path,
    pattern: str,
    glob: str | None,
    timeout_s: float,
) -> list[str] | None:
    cmd = [ag_bin, "--nocolor", "--noheading", "-l"]
    if glob:
        cmd.extend(["-G", _glob_to_ag_file_regex(glob)])
    cmd.extend([pattern, str(search_path)])

    completed = _run_ag_subprocess(cmd, timeout_s=timeout_s)
    if completed is None:
        return None
    if completed.returncode not in (0, 1):
        logger.warning(
            "ag grep exited %s: %s; falling back to Python walk",
            completed.returncode,
            (completed.stderr or completed.stdout or "").strip()[:200],
        )
        return None

    stdout = completed.stdout or ""
    return [
        _to_workspace_relative(workspace, line.strip())
        for line in stdout.splitlines()
        if line.strip()
    ]


def _grep_with_ag_count(
    *,
    ag_bin: str,
    workspace: Path,
    search_path: Path,
    pattern: str,
    glob: str | None,
    timeout_s: float,
) -> str | None:
    cmd = [ag_bin, "--nocolor", "--noheading", "--stats"]
    if glob:
        cmd.extend(["-G", _glob_to_ag_file_regex(glob)])
    cmd.extend([pattern, str(search_path)])

    completed = _run_ag_subprocess(cmd, timeout_s=timeout_s)
    if completed is None:
        return None
    if completed.returncode not in (0, 1):
        logger.warning(
            "ag grep exited %s: %s; falling back to Python walk",
            completed.returncode,
            (completed.stderr or completed.stdout or "").strip()[:200],
        )
        return None

    stdout = completed.stdout or ""
    total = _parse_ag_stats_match_count(stdout)
    if total is None:
        return None
    return str(total)


def _grep_with_ag_content_paths(
    *,
    ag_bin: str,
    workspace: Path,
    pattern: str,
    glob: str | None,
    timeout_s: float,
    paths: list[Path],
) -> GrepResult | None:
    cmd = [ag_bin, "--nocolor", "--noheading", "-n", "--column"]
    if glob:
        cmd.extend(["-G", _glob_to_ag_file_regex(glob)])
    cmd.append(pattern)
    cmd.extend(str(p) for p in paths)

    completed = _run_ag_subprocess(cmd, timeout_s=timeout_s)
    if completed is None:
        return None
    if completed.returncode not in (0, 1):
        logger.warning(
            "ag grep exited %s: %s; falling back to Python walk",
            completed.returncode,
            (completed.stderr or completed.stdout or "").strip()[:200],
        )
        return None

    stdout = completed.stdout or ""
    matches = _parse_ag_content_lines(workspace, stdout, pattern)
    return GrepResult(
        matches=matches,
        files_searched=len({m.path for m in matches}),
        total_matches=len(matches),
    )


def _run_ag_subprocess(
    cmd: list[str], *, timeout_s: float
) -> subprocess.CompletedProcess[str] | None:
    """Run ``ag`` with explicit FD management and graceful error handling.

    Uses Popen for explicit control over file descriptor lifecycle.
    On FD exhaustion (errno 24), logs actionable guidance before fallback.
    """
    stdout_path: str | None = None
    stdout_fh: object | None = None
    stderr_fh: object | None = None
    proc: subprocess.Popen | None = None

    try:
        with tempfile.NamedTemporaryFile(mode="w+", delete=False, suffix=".agout") as tmp:
            stdout_path = tmp.name

        # Open output file explicitly for Popen
        stdout_fh = open(stdout_path, "w", encoding="utf-8")
        proc = subprocess.Popen(
            cmd,
            stdout=stdout_fh,
            stderr=subprocess.PIPE,
            text=True,
        )
        stderr_fh = proc.stderr

        # Wait with timeout
        try:
            proc.wait(timeout=timeout_s)
        except subprocess.TimeoutExpired:
            proc.kill()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                pass  # Process killed, move on
            logger.warning("ag grep timed out after %ss; falling back to Python walk", timeout_s)
            return None

        # Read captured output
        with open(stdout_path, encoding="utf-8") as f:
            stdout_content = f.read()

        stderr_content = ""
        if stderr_fh is not None:
            try:
                stderr_content = stderr_fh.read()
            except OSError:
                pass

        return subprocess.CompletedProcess(
            args=cmd,
            returncode=proc.returncode,
            stdout=stdout_content,
            stderr=stderr_content,
        )

    except OSError as exc:
        # EMFILE (errno 24) = too many open files
        if exc.errno == 24:
            logger.warning(
                "ag grep hit system FD limit (errno 24); falling back to Python walk. "
                "Consider increasing: ulimit -n 1024"
            )
        else:
            logger.warning("ag grep failed (%s); falling back to Python walk", exc)
        return None

    except subprocess.TimeoutExpired:
        logger.warning("ag grep timed out after %ss; falling back to Python walk", timeout_s)
        return None

    finally:
        # Explicit cleanup order: stderr -> stdout -> process -> temp file
        if stderr_fh is not None:
            try:
                stderr_fh.close()
            except OSError:
                pass
        if stdout_fh is not None:
            try:
                stdout_fh.close()
            except OSError:
                pass
        if proc is not None:
            # Ensure process is terminated
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    proc.kill()
        if stdout_path is not None:
            try:
                os.unlink(stdout_path)
            except OSError:
                pass


def _glob_to_ag_file_regex(glob: str) -> str:
    """Convert a shell glob to a regex for ``ag -G`` (filename filter)."""
    return fnmatch.translate(glob)


def _resolve_ag_paths(workspace: Path, rel_paths: list[str]) -> list[Path]:
    """Resolve workspace-relative paths to absolute paths for ``ag``."""
    resolved: list[Path] = []
    workspace_resolved = workspace.resolve()
    for rel in rel_paths:
        candidate = (workspace_resolved / rel).resolve()
        try:
            candidate.relative_to(workspace_resolved)
        except ValueError:
            continue
        if candidate.is_file():
            resolved.append(candidate)
    return resolved


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
