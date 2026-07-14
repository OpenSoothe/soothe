"""Fast grep via ``ag`` (The Silver Searcher) or ``rg`` (ripgrep)."""

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

_GREP_TIMEOUT_S = 120
_AG_ENV_VAR = "SOOTHE_AG_PATH"
_RG_ENV_VAR = "SOOTHE_RG_PATH"
_AG_COMMON_PATHS: tuple[str, ...] = (
    "/opt/homebrew/bin/ag",
    "/usr/local/bin/ag",
    "/usr/bin/ag",
)
_RG_COMMON_PATHS: tuple[str, ...] = (
    "/opt/homebrew/bin/rg",
    "/usr/local/bin/rg",
    "/usr/bin/rg",
)
_ag_bin_cache: str | None = None
_ag_bin_resolved: bool = False
_rg_bin_cache: str | None = None
_rg_bin_resolved: bool = False

GREP_UNAVAILABLE_ERROR = (
    "grep requires 'ag' (The Silver Searcher) or 'rg' (ripgrep). "
    "Install one: brew install ripgrep the_silver_searcher"
)


def get_ag_bin() -> str | None:
    """Return cached path to the ``ag`` binary, or ``None`` when unavailable."""
    global _ag_bin_cache, _ag_bin_resolved
    if not _ag_bin_resolved:
        _ag_bin_cache = _resolve_executable("ag", _AG_ENV_VAR, _AG_COMMON_PATHS)
        _ag_bin_resolved = True
    return _ag_bin_cache


def get_rg_bin() -> str | None:
    """Return cached path to the ``rg`` binary, or ``None`` when unavailable."""
    global _rg_bin_cache, _rg_bin_resolved
    if not _rg_bin_resolved:
        _rg_bin_cache = _resolve_executable("rg", _RG_ENV_VAR, _RG_COMMON_PATHS)
        _rg_bin_resolved = True
    return _rg_bin_cache


def is_grep_available() -> bool:
    """Return whether ``ag`` or ``rg`` is available."""
    return get_ag_bin() is not None or get_rg_bin() is not None


def reset_grep_backend_cache() -> None:
    """Clear cached search-binary paths (for tests)."""
    global _ag_bin_cache, _ag_bin_resolved, _rg_bin_cache, _rg_bin_resolved
    _ag_bin_cache = None
    _ag_bin_resolved = False
    _rg_bin_cache = None
    _rg_bin_resolved = False


def _resolve_executable(name: str, env_var: str, common_paths: tuple[str, ...]) -> str | None:
    """Resolve a search binary across env override, PATH, and common locations."""
    env_path = os.environ.get(env_var)
    if env_path:
        resolved = _normalize_executable(env_path)
        if resolved is not None:
            return resolved
        logger.debug("%s is set but not an executable %s binary: %s", env_var, name, env_path)

    which_path = shutil.which(name)
    if which_path:
        resolved = _normalize_executable(which_path)
        if resolved is not None:
            return resolved

    for candidate in common_paths:
        resolved = _normalize_executable(candidate)
        if resolved is not None:
            logger.debug("Resolved %s via common path: %s", name, resolved)
            return resolved

    return None


def _normalize_executable(path: str) -> str | None:
    """Return ``path`` when it points to an executable file."""
    candidate = Path(path).expanduser()
    if candidate.is_file() and os.access(candidate, os.X_OK):
        return str(candidate.resolve())
    return None


def run_grep(
    *,
    workspace: Path,
    search_path: Path,
    pattern: str,
    glob: str | None,
    output_mode: str,
    timeout_s: float = _GREP_TIMEOUT_S,
) -> GrepResult | list[str] | str | None:
    """Run ``ag`` or ``rg`` when available.

    Returns:
        Parsed grep output, or ``None`` when both backends are unavailable or fail.
    """
    ag_bin = get_ag_bin()
    if ag_bin is not None:
        return _grep_with_backend(
            backend="ag",
            bin_path=ag_bin,
            workspace=workspace,
            search_path=search_path,
            pattern=pattern,
            glob=glob,
            output_mode=output_mode,
            timeout_s=timeout_s,
        )

    rg_bin = get_rg_bin()
    if rg_bin is not None:
        return _grep_with_backend(
            backend="rg",
            bin_path=rg_bin,
            workspace=workspace,
            search_path=search_path,
            pattern=pattern,
            glob=glob,
            output_mode=output_mode,
            timeout_s=timeout_s,
        )

    return None


def _grep_with_backend(
    *,
    backend: str,
    bin_path: str,
    workspace: Path,
    search_path: Path,
    pattern: str,
    glob: str | None,
    output_mode: str,
    timeout_s: float,
) -> GrepResult | list[str] | str | None:
    if output_mode == "files_with_matches":
        return _grep_files_with_backend(
            backend=backend,
            bin_path=bin_path,
            workspace=workspace,
            search_path=search_path,
            pattern=pattern,
            glob=glob,
            timeout_s=timeout_s,
        )

    if output_mode == "count":
        return _grep_count_with_backend(
            backend=backend,
            bin_path=bin_path,
            workspace=workspace,
            search_path=search_path,
            pattern=pattern,
            glob=glob,
            timeout_s=timeout_s,
        )

    if search_path.is_file():
        return _grep_content_paths_with_backend(
            backend=backend,
            bin_path=bin_path,
            workspace=workspace,
            pattern=pattern,
            glob=glob,
            timeout_s=timeout_s,
            paths=[search_path],
        )

    files = _grep_files_with_backend(
        backend=backend,
        bin_path=bin_path,
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

    abs_paths = _resolve_search_paths(workspace, files)
    if not abs_paths:
        return GrepResult(matches=[], files_searched=0, total_matches=0)

    return _grep_content_paths_with_backend(
        backend=backend,
        bin_path=bin_path,
        workspace=workspace,
        pattern=pattern,
        glob=glob,
        timeout_s=timeout_s,
        paths=abs_paths,
    )


def _grep_files_with_backend(
    *,
    backend: str,
    bin_path: str,
    workspace: Path,
    search_path: Path,
    pattern: str,
    glob: str | None,
    timeout_s: float,
) -> list[str] | None:
    if backend == "ag":
        cmd = [bin_path, "--nocolor", "--noheading", "-l"]
        if glob:
            cmd.extend(["-G", _glob_to_ag_file_regex(glob)])
        cmd.extend([pattern, str(search_path)])
    else:
        cmd = [bin_path, "--no-heading", "-l"]
        if glob:
            cmd.extend(["--glob", glob])
        cmd.extend(["--", pattern, str(search_path)])

    completed = _run_grep_subprocess(cmd, backend=backend, timeout_s=timeout_s)
    if completed is None:
        return None
    if completed.returncode not in (0, 1):
        logger.warning(
            "%s grep exited %s: %s",
            backend,
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


def _grep_count_with_backend(
    *,
    backend: str,
    bin_path: str,
    workspace: Path,
    search_path: Path,
    pattern: str,
    glob: str | None,
    timeout_s: float,
) -> str | None:
    if backend == "ag":
        cmd = [bin_path, "--nocolor", "--noheading", "--stats"]
        if glob:
            cmd.extend(["-G", _glob_to_ag_file_regex(glob)])
        cmd.extend([pattern, str(search_path)])

        completed = _run_grep_subprocess(cmd, backend=backend, timeout_s=timeout_s)
        if completed is None:
            return None
        if completed.returncode not in (0, 1):
            logger.warning(
                "%s grep exited %s: %s",
                backend,
                completed.returncode,
                (completed.stderr or completed.stdout or "").strip()[:200],
            )
            return None

        total = _parse_match_count_stats(completed.stdout or "")
        return None if total is None else str(total)

    cmd = [bin_path, "--no-heading", "-c"]
    if glob:
        cmd.extend(["--glob", glob])
    cmd.extend(["--", pattern, str(search_path)])

    completed = _run_grep_subprocess(cmd, backend=backend, timeout_s=timeout_s)
    if completed is None:
        return None
    if completed.returncode not in (0, 1):
        logger.warning(
            "%s grep exited %s: %s",
            backend,
            completed.returncode,
            (completed.stderr or completed.stdout or "").strip()[:200],
        )
        return None

    total = 0
    for line in (completed.stdout or "").splitlines():
        if not line.strip():
            continue
        try:
            total += int(line.rsplit(":", 1)[-1])
        except ValueError:
            continue
    return str(total)


def _grep_content_paths_with_backend(
    *,
    backend: str,
    bin_path: str,
    workspace: Path,
    pattern: str,
    glob: str | None,
    timeout_s: float,
    paths: list[Path],
) -> GrepResult | None:
    if backend == "ag":
        cmd = [bin_path, "--nocolor", "--noheading", "-n", "--column"]
        if glob:
            cmd.extend(["-G", _glob_to_ag_file_regex(glob)])
        cmd.append(pattern)
        cmd.extend(str(p) for p in paths)
    else:
        cmd = [bin_path, "--no-heading", "-n"]
        if glob:
            cmd.extend(["--glob", glob])
        cmd.append(pattern)
        cmd.extend(str(p) for p in paths)

    completed = _run_grep_subprocess(cmd, backend=backend, timeout_s=timeout_s)
    if completed is None:
        return None
    if completed.returncode not in (0, 1):
        logger.warning(
            "%s grep exited %s: %s",
            backend,
            completed.returncode,
            (completed.stderr or completed.stdout or "").strip()[:200],
        )
        return None

    stdout = completed.stdout or ""
    matches = _parse_content_lines(workspace, stdout, pattern)
    return GrepResult(
        matches=matches,
        files_searched=len({m.path for m in matches}),
        total_matches=len(matches),
    )


def _run_grep_subprocess(
    cmd: list[str], *, backend: str, timeout_s: float
) -> subprocess.CompletedProcess[str] | None:
    """Run ``ag``/``rg`` with explicit FD management and graceful error handling."""
    stdout_path: str | None = None
    stdout_fh: object | None = None
    stderr_fh: object | None = None
    proc: subprocess.Popen | None = None

    try:
        with tempfile.NamedTemporaryFile(mode="w+", delete=False, suffix=f".{backend}out") as tmp:
            stdout_path = tmp.name

        stdout_fh = open(stdout_path, "w", encoding="utf-8")
        proc = subprocess.Popen(
            cmd,
            stdout=stdout_fh,
            stderr=subprocess.PIPE,
            text=True,
        )
        stderr_fh = proc.stderr

        try:
            proc.wait(timeout=timeout_s)
        except subprocess.TimeoutExpired:
            proc.kill()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                pass
            logger.warning("%s grep timed out after %ss", backend, timeout_s)
            return None

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
        if exc.errno == 24:
            logger.warning(
                "%s grep hit system FD limit (errno 24). Consider increasing: ulimit -n 1024",
                backend,
            )
        else:
            logger.warning("%s grep failed (%s)", backend, exc)
        return None

    except subprocess.TimeoutExpired:
        logger.warning("%s grep timed out after %ss", backend, timeout_s)
        return None

    finally:
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
        if proc is not None and proc.poll() is None:
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


def _resolve_search_paths(workspace: Path, rel_paths: list[str]) -> list[Path]:
    """Resolve workspace-relative or host-absolute paths for content search."""
    resolved: list[Path] = []
    workspace_resolved = workspace.resolve()
    for rel in rel_paths:
        candidate = Path(rel)
        if not candidate.is_absolute():
            candidate = (workspace_resolved / rel).resolve()
        else:
            candidate = candidate.resolve()
        if candidate.is_file():
            resolved.append(candidate)
    return resolved


def _parse_match_count_stats(stdout: str) -> int | None:
    """Parse ``ag --stats`` output for total match count."""
    for line in stdout.splitlines():
        stripped = line.strip()
        if stripped.startswith("matches found:"):
            try:
                return int(stripped.split(":", 1)[1].strip())
            except ValueError:
                return None
    return 0


def _parse_content_lines(workspace: Path, stdout: str, pattern: str) -> list[GrepMatch]:
    """Parse ``ag``/``rg`` ``-n`` lines into ``GrepMatch`` rows."""
    matches: list[GrepMatch] = []
    for line in stdout.splitlines():
        if not line.strip():
            continue
        parsed = _parse_match_line(line)
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


def _parse_match_line(line: str) -> tuple[str, int, str] | None:
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
    """Normalize search output paths to workspace-relative or host-absolute strings."""
    path = Path(file_path)
    if not path.is_absolute():
        return str(path)
    try:
        return str(path.resolve().relative_to(workspace.resolve()))
    except ValueError:
        return str(path)
