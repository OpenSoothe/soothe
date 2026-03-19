"""Built-in skills for Soothe agent framework."""

from importlib.resources import files
from pathlib import Path


def get_built_in_skills_paths() -> list[str]:
    """Get filesystem paths to all built-in skills.

    Uses importlib.resources to find skills whether installed from wheel or running from source.

    Returns:
        List of directory paths containing SKILL.md files.
    """
    try:
        # Get the skills package location using modern importlib.resources API
        skills_package = files("soothe.skills")

        # Convert to Path if it's a MultiplexedPath or similar
        if hasattr(skills_package, "_paths"):
            # Handle MultiplexedPath (e.g., when in editable install)
            base_paths = [Path(str(p)) for p in skills_package._paths]
        else:
            base_paths = [Path(str(skills_package))]

        skill_dirs = []
        for base_path in base_paths:
            if not base_path.exists():
                continue

            # Find all subdirectories containing SKILL.md
            for skill_dir in base_path.iterdir():
                if skill_dir.is_dir():
                    skill_file = skill_dir / "SKILL.md"
                    if skill_file.exists():
                        skill_dirs.append(str(skill_dir))

    except (TypeError, AttributeError, FileNotFoundError):
        # Fallback for development/editable installs
        import soothe.skills

        base_path = Path(soothe.skills.__file__).parent
        skill_dirs = []

        for skill_dir in base_path.iterdir():
            if skill_dir.is_dir():
                skill_file = skill_dir / "SKILL.md"
                if skill_file.exists():
                    skill_dirs.append(str(skill_dir))

        return skill_dirs
    else:
        return skill_dirs


__all__ = ["get_built_in_skills_paths"]
