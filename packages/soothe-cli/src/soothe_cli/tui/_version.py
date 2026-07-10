"""Version information and lightweight constants for `soothe`."""

from __future__ import annotations

import json
import logging
import re
from importlib.metadata import PackageNotFoundError, distribution, version
from pathlib import Path
from urllib.parse import unquote, urlparse

logger = logging.getLogger(__name__)

_VERSION_PATTERN = re.compile(r"^(\d+\.\d+\.\d+)")


def _parse_version_file_text(text: str) -> str | None:
    """Extract the semver from a repo ``VERSION`` file."""
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        match = _VERSION_PATTERN.match(stripped)
        if match:
            return match.group(1)
    return None


def _editable_source_roots() -> list[Path]:
    """Return resolved source roots for editable Soothe packages."""
    roots: list[Path] = []
    seen: set[Path] = set()
    for dist_name in ("soothe-cli", "soothe", "Soothe"):
        try:
            dist = distribution(dist_name)
        except PackageNotFoundError:
            continue
        try:
            raw = dist.read_text("direct_url.json")
        except (FileNotFoundError, OSError):
            continue
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            logger.debug("Invalid direct_url.json for %s", dist_name, exc_info=True)
            continue
        if not data.get("dir_info", {}).get("editable"):
            continue
        url = data.get("url", "")
        if not url.startswith("file://"):
            continue
        root = Path(unquote(urlparse(url).path)).resolve()
        if root not in seen:
            seen.add(root)
            roots.append(root)
    return roots


def _read_repo_version_from_source(root: Path) -> str | None:
    """Read the monorepo ``VERSION`` file for an editable install root."""
    candidates = [root.parent.parent / "VERSION", *(parent / "VERSION" for parent in root.parents)]
    for path in candidates:
        if not path.is_file():
            continue
        try:
            parsed = _parse_version_file_text(path.read_text(encoding="utf-8"))
        except OSError:
            logger.debug("Failed to read VERSION file at %s", path, exc_info=True)
            continue
        if parsed:
            return parsed
    return None


def _resolve_version() -> str:
    """Resolve the CLI version, preferring repo ``VERSION`` for editable installs."""
    for root in _editable_source_roots():
        repo_version = _read_repo_version_from_source(root)
        if repo_version:
            return repo_version

    for pkg in ("soothe-cli", "soothe"):
        try:
            return version(pkg)
        except PackageNotFoundError:
            continue
    return "0.0.0"


def is_editable_install() -> bool:
    """Return whether Soothe is installed in editable mode."""
    return bool(_editable_source_roots())


def editable_install_display_path() -> str | None:
    """Return a ``~``-contracted source path for editable installs."""
    roots = _editable_source_roots()
    if not roots:
        return None

    install_root = roots[0]
    for root in roots:
        if root.name == "soothe-cli":
            install_root = root
            break

    path = str(install_root)
    home = str(Path.home())
    if path.startswith(home):
        return "~" + path[len(home) :]
    return path


__version__ = _resolve_version()

DOCS_URL = "https://github.com/mirasoth/soothe/docs"
"""URL for Soothe documentation."""

PYPI_URL = "https://pypi.org/pypi/soothe/json"
"""PyPI JSON API endpoint for version checks."""

CHANGELOG_URL = "https://github.com/mirasoth/soothe/blob/main/CHANGELOG.md"
"""URL for the full changelog."""

USER_AGENT = f"soothe/{__version__} update-check"
"""User-Agent header sent with PyPI requests."""
