"""Mirror external skill directories into the workspace for virtual-mode filesystem access."""

from __future__ import annotations

import logging
import shutil
from pathlib import Path
from typing import TYPE_CHECKING

from soothe.skills.builtins import get_built_in_skills_paths, is_builtin_skill_directory

if TYPE_CHECKING:
    from soothe.config import SootheConfig

logger = logging.getLogger(__name__)


def skill_directories_for_resolution(
    config: SootheConfig,
    workspace: str | Path,
) -> list[str]:
    """Skill directory search order; workspace mirror paths are last (win on name clash)."""
    ws = str(Path(workspace).expanduser().resolve())
    dirs: list[str] = list(get_built_in_skills_paths(ws))
    if config.skills:
        dirs.extend(config.skills)
    mirror = workspace_skills_mirror_root(ws)
    if mirror.is_dir():
        for skill_md in mirror.glob("*/SKILL.md"):
            dirs.append(str(skill_md.parent.resolve()))
    return dirs


def workspace_skills_mirror_root(workspace: str | Path) -> Path:
    """Return ``<workspace>/.soothe/skills`` (created by callers when syncing)."""
    return Path(workspace).expanduser().resolve() / ".soothe" / "skills"


def is_path_under_workspace(path: Path, workspace: Path) -> bool:
    """Return True when ``path`` resolves inside ``workspace``."""
    try:
        path.resolve().relative_to(workspace.resolve())
    except ValueError:
        return False
    else:
        return True


def _tree_max_mtime(root: Path) -> float:
    latest = root.stat().st_mtime
    for entry in root.rglob("*"):
        if entry.is_file():
            latest = max(latest, entry.stat().st_mtime)
    return latest


def _mirror_is_current(src: Path, dest: Path) -> bool:
    if not dest.is_dir():
        return False
    try:
        return _tree_max_mtime(dest) >= _tree_max_mtime(src)
    except OSError:
        return False


def sync_skill_directory_to_workspace(
    src: Path,
    workspace: Path,
    *,
    skill_name: str,
) -> Path:
    """Copy ``src`` skill tree to ``<workspace>/.soothe/skills/<skill_name>``.

    Args:
        src: Host skill directory (contains ``SKILL.md``).
        workspace: Resolved workspace root.
        skill_name: Canonical skill name (directory name under the mirror).

    Returns:
        Resolved destination directory path.
    """
    dest_root = workspace_skills_mirror_root(workspace)
    dest_root.mkdir(parents=True, exist_ok=True)
    dest = dest_root / skill_name
    src_resolved = src.resolve()

    if _mirror_is_current(src_resolved, dest):
        return dest.resolve()

    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(src_resolved, dest)
    return dest.resolve()


def collect_external_skills_to_mirror(
    config: SootheConfig,
    workspace: str | Path,
) -> dict[str, Path]:
    """Map skill name → host source dir for skills outside the workspace (non-builtin).

    Last-wins across discovery order matches ``resolve_skill_directory``.

    Args:
        config: Active Soothe configuration (extra ``config.skills`` paths).
        workspace: Resolved workspace root.

    Returns:
        Dict of skill name to source directory on the host filesystem.
    """
    ws = Path(workspace).expanduser().resolve()
    from soothe.skills.catalog import _parse_skill_directory

    by_name: dict[str, Path] = {}
    all_dirs: list[str] = list(get_built_in_skills_paths(str(ws)))
    if config.skills:
        all_dirs.extend(config.skills)
    for dir_path in all_dirs:
        if is_builtin_skill_directory(dir_path):
            continue
        src = Path(dir_path).expanduser().resolve()
        if not src.is_dir():
            continue
        if is_path_under_workspace(src, ws):
            continue
        meta = _parse_skill_directory(dir_path)
        if meta is None:
            continue
        skill_name = str(meta.get("name") or src.name).strip()
        if not skill_name:
            continue
        by_name[skill_name] = src
    return by_name


def sync_external_skills_to_workspace(
    config: SootheConfig,
    workspace: str | Path,
) -> dict[str, str]:
    """Mirror external skills into ``<workspace>/.soothe/skills/<name>``.

    Built-in package skills are not copied. Skills already under the workspace are
    skipped.

    Args:
        config: Active Soothe configuration.
        workspace: Workspace root for the current run.

    Returns:
        Map of skill name → mirrored absolute path under the workspace.
    """
    ws = Path(workspace).expanduser().resolve()
    mirrored: dict[str, str] = {}
    for skill_name, src in collect_external_skills_to_mirror(config, ws).items():
        try:
            dest = sync_skill_directory_to_workspace(src, ws, skill_name=skill_name)
        except OSError:
            logger.warning(
                "Failed to mirror skill %s from %s into workspace",
                skill_name,
                src,
                exc_info=True,
            )
            continue
        mirrored[skill_name] = str(dest)
        logger.debug("Mirrored skill %s: %s -> %s", skill_name, src, dest)
    return mirrored
