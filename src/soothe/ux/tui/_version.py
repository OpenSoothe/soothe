"""Version information and lightweight constants for `soothe`."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("soothe")
except PackageNotFoundError:
    # Fallback for development/editable installs
    __version__ = "0.0.0"

DOCS_URL = "https://github.com/caesar0301/soothe/docs"
"""URL for Soothe documentation."""

PYPI_URL = "https://pypi.org/pypi/soothe/json"
"""PyPI JSON API endpoint for version checks."""

CHANGELOG_URL = "https://github.com/caesar0301/soothe/blob/main/CHANGELOG.md"
"""URL for the full changelog."""

USER_AGENT = f"soothe/{__version__} update-check"
"""User-Agent header sent with PyPI requests."""
