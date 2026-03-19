"""Init command for Soothe CLI."""

import shutil
from importlib.resources import as_file, files
from pathlib import Path

import typer

from soothe.config import SOOTHE_HOME


def init_soothe() -> None:
    """Initialize ~/.soothe with a default configuration."""
    home = Path(SOOTHE_HOME).expanduser()
    target = home / "config" / "config.yml"

    if target.exists():
        typer.echo(f"Config already exists at {target}")
        return

    target.parent.mkdir(parents=True, exist_ok=True)

    # Try loading from installed package resources first
    template_found = False
    try:
        config_resource = files("soothe.config").joinpath("config.yml")
        with as_file(config_resource) as template_path:
            if template_path.exists():
                shutil.copy2(template_path, target)
                typer.echo(f"Created {target}")
                template_found = True
    except (FileNotFoundError, TypeError, AttributeError):
        pass

    # Fallback for development/editable installs - check repo root
    if not template_found:
        template = Path(__file__).resolve().parent.parent.parent.parent / "config" / "config.yml"
        if template.exists():
            shutil.copy2(template, target)
            typer.echo(f"Created {target}")
            template_found = True

    # Create minimal config if template not found anywhere
    if not template_found:
        target.write_text("# Soothe configuration\n# See docs/user_guide.md for options\n")
        typer.echo(f"Created minimal {target}")

    for subdir in ("runs", "generated_agents", "logs"):
        (home / subdir).mkdir(parents=True, exist_ok=True)

    typer.echo(f"Soothe home initialized at {home}")
