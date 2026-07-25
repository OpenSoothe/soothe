"""Host tool binary health checks (rg, fd, git)."""

from __future__ import annotations

import shutil
import subprocess
from typing import Any

from soothe_daemon.health.formatters import aggregate_status
from soothe_daemon.health.models import CategoryResult, CheckResult, CheckStatus


def _bin_version(bin_path: str) -> str | None:
    """Return first line of ``--version`` output, or None on failure."""
    try:
        result = subprocess.run(  # noqa: S603
            [bin_path, "--version"],
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
        )
        line = (result.stdout or result.stderr or "").strip().splitlines()
        return line[0].strip() if line else None
    except (OSError, subprocess.TimeoutExpired):
        return None


def _check_rg() -> CheckResult:
    """Check ripgrep availability (preferred filesystem search backend)."""
    path = shutil.which("rg") or shutil.which("rg.exe")

    if not path:
        return CheckResult(
            name="rg",
            status=CheckStatus.WARNING,
            message="rg (ripgrep) not found — search falls back to Python",
            details={
                "remediation": "Install ripgrep (e.g. brew install ripgrep / apt install ripgrep)",
            },
        )

    version = _bin_version(path)
    details: dict[str, Any] = {"path": path}
    if version:
        details["version"] = version
    msg = f"rg available: {path}"
    if version:
        msg = f"rg available: {path} ({version})"
    return CheckResult(name="rg", status=CheckStatus.OK, message=msg, details=details)


def _check_fd() -> CheckResult:
    """Check fd / fdfind availability (preferred glob backend)."""
    path = shutil.which("fd") or shutil.which("fdfind") or shutil.which("fd.exe")

    if not path:
        return CheckResult(
            name="fd",
            status=CheckStatus.WARNING,
            message="fd not found — glob falls back to Python",
            details={
                "remediation": "Install fd (e.g. brew install fd / apt install fd-find)",
            },
        )

    version = _bin_version(path)
    details: dict[str, Any] = {"path": path}
    if version:
        details["version"] = version
    msg = f"fd available: {path}"
    if version:
        msg = f"fd available: {path} ({version})"
    return CheckResult(name="fd", status=CheckStatus.OK, message=msg, details=details)


def _check_git() -> CheckResult:
    """Check git binary (optional; used by many agent workflows)."""
    path = shutil.which("git")
    if not path:
        return CheckResult(
            name="git",
            status=CheckStatus.INFO,
            message="git not found (optional)",
            details={"remediation": "Install git if repository workflows are needed"},
        )
    version = _bin_version(path)
    details: dict[str, Any] = {"path": path}
    if version:
        details["version"] = version
    msg = f"git available: {path}"
    if version:
        msg = f"git available: {path} ({version})"
    return CheckResult(name="git", status=CheckStatus.OK, message=msg, details=details)


async def check_tool_deps() -> CategoryResult:
    """Check host tool binaries used by CoreAgent filesystem tools.

    Returns:
        CategoryResult for the ``tool_deps`` category.
    """
    checks = [_check_rg(), _check_fd(), _check_git()]
    return CategoryResult(
        category="tool_deps",
        status=aggregate_status([c.status for c in checks]),
        checks=checks,
    )
