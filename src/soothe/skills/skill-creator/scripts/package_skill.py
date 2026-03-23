#!/usr/bin/env python3
"""Skill Packager - Creates a distributable .skill file of a skill folder.

Usage:
    python package_skill.py <path/to/skill-folder> [output-directory]

Example:
    python package_skill.py skills/public/my-skill
    python package_skill.py skills/public/my-skill ./dist
"""

import sys
import zipfile
from pathlib import Path

from quick_validate import validate_skill


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _cleanup_partial_archive(skill_filename: Path) -> None:
    try:
        if skill_filename.exists():
            skill_filename.unlink()
    except OSError:
        pass


def package_skill(skill_path, output_dir=None):
    """Package a skill folder into a .skill file.

    Args:
        skill_path: Path to the skill folder
        output_dir: Optional output directory for the .skill file (defaults to current directory)

    Returns:
        Path to the created .skill file, or None if error
    """
    skill_path = Path(skill_path).resolve()

    # Validate skill folder exists
    if not skill_path.exists():
        return None

    if not skill_path.is_dir():
        return None

    # Validate SKILL.md exists
    skill_md = skill_path / "SKILL.md"
    if not skill_md.exists():
        return None

    # Run validation before packaging
    valid, _message = validate_skill(skill_path)
    if not valid:
        return None

    # Determine output location
    skill_name = skill_path.name
    if output_dir:
        output_path = Path(output_dir).resolve()
        output_path.mkdir(parents=True, exist_ok=True)
    else:
        output_path = Path.cwd()

    skill_filename = output_path / f"{skill_name}.skill"

    EXCLUDED_DIRS = {".git", ".svn", ".hg", "__pycache__", "node_modules"}

    files_to_package = []
    resolved_archive = skill_filename.resolve()

    for file_path in skill_path.rglob("*"):
        # Fail closed on symlinks so the packaged contents are explicit and predictable.
        if file_path.is_symlink():
            _cleanup_partial_archive(skill_filename)
            return None

        rel_parts = file_path.relative_to(skill_path).parts
        if any(part in EXCLUDED_DIRS for part in rel_parts):
            continue

        if file_path.is_file():
            resolved_file = file_path.resolve()
            if not _is_within(resolved_file, skill_path):
                _cleanup_partial_archive(skill_filename)
                return None
            # If output lives under skill_path, avoid writing archive into itself.
            if resolved_file == resolved_archive:
                continue
            files_to_package.append(file_path)

    # Create the .skill file (zip format)
    try:
        with zipfile.ZipFile(skill_filename, "w", zipfile.ZIP_DEFLATED) as zipf:
            for file_path in files_to_package:
                # Calculate the relative path within the zip.
                arcname = Path(skill_name) / file_path.relative_to(skill_path)
                zipf.write(file_path, arcname)

        return skill_filename

    except Exception:
        _cleanup_partial_archive(skill_filename)
        return None


def main() -> None:
    if len(sys.argv) < 2:
        sys.exit(1)

    skill_path = sys.argv[1]
    output_dir = sys.argv[2] if len(sys.argv) > 2 else None

    if output_dir:
        pass

    result = package_skill(skill_path, output_dir)

    if result:
        sys.exit(0)
    else:
        sys.exit(1)


if __name__ == "__main__":
    main()
