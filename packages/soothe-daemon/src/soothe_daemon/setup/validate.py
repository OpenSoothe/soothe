"""Phase 4–5: validate loaded configs and optional provider doctor check."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import TextIO


def validate_configs(
    *,
    nano_path: Path,
    soothe_path: Path,
    daemon_path: Path,
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,
) -> bool:
    """Load configs with Pydantic; return True on success."""
    out = stdout if stdout is not None else sys.stdout
    err = stderr if stderr is not None else sys.stderr

    from soothe.config import SootheConfig

    from soothe_daemon.config import SootheDaemonConfig

    ok = True
    try:
        if soothe_path.is_file():
            SootheConfig.from_split_yaml_files(
                nano_path=str(nano_path),
                soothe_path=str(soothe_path),
            )
        else:
            SootheConfig.from_yaml_file(str(nano_path))
        out.write("  agent config: OK\n")
    except Exception as exc:
        err.write(f"  agent config: FAILED ({exc})\n")
        ok = False

    try:
        SootheDaemonConfig.from_yaml_file(str(daemon_path))
        out.write("  daemon config: OK\n")
    except Exception as exc:
        err.write(f"  daemon config: FAILED ({exc})\n")
        ok = False

    return ok


async def run_provider_doctor(
    *,
    nano_path: Path,
    soothe_path: Path,
    daemon_path: Path,
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,
) -> None:
    """Run provider health checks; warnings only (never rolls back files)."""
    out = stdout if stdout is not None else sys.stdout
    err = stderr if stderr is not None else sys.stderr

    from soothe.config import SootheConfig

    from soothe_daemon.config import SootheDaemonConfig
    from soothe_daemon.health.checker import HealthChecker
    from soothe_daemon.health.models import CheckStatus

    try:
        if soothe_path.is_file():
            cfg = SootheConfig.from_split_yaml_files(
                nano_path=str(nano_path),
                soothe_path=str(soothe_path),
            )
        else:
            cfg = SootheConfig.from_yaml_file(str(nano_path))
        daemon_cfg = SootheDaemonConfig.from_yaml_file(str(daemon_path))
    except Exception as exc:
        err.write(f"  doctor skipped (config load failed): {exc}\n")
        return

    checker = HealthChecker(cfg, daemon_config=daemon_cfg)
    report = await checker.run_all_checks(categories=["providers"])
    status = report.overall_status
    if status == CheckStatus.OK:
        out.write("  providers: OK\n")
        return
    if status == CheckStatus.WARNING:
        out.write("  providers: WARNING (config saved; fix keys/endpoint if needed)\n")
        return
    out.write("  providers: ERROR (config saved; run `soothed doctor` for details)\n")
