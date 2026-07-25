"""Phase 1–2: scaffold missing YAML configs from templates."""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path

from soothe_daemon.setup.atomic import atomic_write_text
from soothe_daemon.setup.paths import TEMPLATE_NAMES, config_paths, read_template_text


@dataclass
class ScaffoldResult:
    """Outcome of the scaffold phase."""

    config_dir: Path
    created: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    overwritten: list[str] = field(default_factory=list)


def scaffold_configs(
    config_dir: Path,
    *,
    force: bool = False,
    stdout: object | None = None,
) -> ScaffoldResult:
    """Create missing ``nano.yml`` / ``soothe.yml`` / ``daemon.yml`` from templates.

    Args:
        config_dir: Target directory (created if missing).
        force: When True, overwrite existing files with templates.
        stdout: Optional stream for progress messages (defaults to ``sys.stdout``).

    Returns:
        ScaffoldResult describing created / skipped / overwritten files.
    """
    out = stdout if stdout is not None else sys.stdout
    config_dir = config_dir.expanduser()
    config_dir.mkdir(parents=True, exist_ok=True)
    paths = config_paths(config_dir)
    result = ScaffoldResult(config_dir=config_dir)

    for template_name in TEMPLATE_NAMES:
        key = template_name.removesuffix(".yml")
        dest = paths[key]
        exists = dest.is_file()
        if exists and not force:
            result.skipped.append(key)
            out.write(f"  keep existing: {dest}\n")
            continue

        content = read_template_text(template_name)
        atomic_write_text(dest, content)
        if exists:
            result.overwritten.append(key)
            out.write(f"  overwritten: {dest}\n")
        else:
            result.created.append(key)
            out.write(f"  created: {dest}\n")

    return result
