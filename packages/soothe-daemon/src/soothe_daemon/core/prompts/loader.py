"""Prompt fragment loader for template loading."""

from __future__ import annotations

import logging
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, Template

logger = logging.getLogger(__name__)

# Shared Jinja2 environment for fragment templates
_env: Environment | None = None


def get_jinja_env() -> Environment:
    """Get or create shared Jinja2 environment.

    Returns:
        Jinja2 Environment with FileSystemLoader.

    Note:
        autoescape=False is intentional for prompt templates that render
        raw text content (not HTML). Prompt fragments are trusted internal
        assets, not user-provided content.
    """
    global _env
    if _env is None:
        fragments_dir = Path(__file__).parent / "fragments"
        _env = Environment(
            loader=FileSystemLoader(str(fragments_dir)),
            autoescape=False,  # noqa: S701 # Intentional for prompt templates (trusted internal assets)
            trim_blocks=True,
            lstrip_blocks=True,
        )
    return _env


def load_prompt_fragment(relative_path: str) -> Template:
    """Load and return a Jinja2 template from fragments directory.

    Args:
        relative_path: Path relative to fragments directory (e.g., "instructions/synthesis_format.xml")

    Returns:
        Jinja2 Template object ready for rendering.

    Raises:
        FileNotFoundError: If fragment file doesn't exist.
    """
    env = get_jinja_env()

    # Normalize path (remove leading/trailing slashes)
    normalized_path = relative_path.strip("/")

    try:
        return env.get_template(normalized_path)
    except Exception:
        msg = f"Fragment not found: {relative_path}"
        logger.exception("Failed to load prompt fragment: %s", relative_path)
        raise FileNotFoundError(msg) from None


__all__ = ["get_jinja_env", "load_prompt_fragment"]
