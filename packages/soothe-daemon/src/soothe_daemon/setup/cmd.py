"""Orchestrate ``soothed setup`` phases."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import TextIO

from soothe_sdk.paths import SOOTHE_HOME

from soothe_daemon.setup.paths import config_paths, resolve_config_dir
from soothe_daemon.setup.provider import (
    ProviderSetupCancelledError,
    ProviderSetupSkippedError,
    merge_provider_from_env,
    run_provider_wizard,
)
from soothe_daemon.setup.scaffold import scaffold_configs
from soothe_daemon.setup.validate import run_provider_doctor, validate_configs


def run_setup(
    *,
    config_dir: str | Path | None = None,
    yes: bool = False,
    force: bool = False,
    skip_provider: bool = False,
    skip_doctor: bool = False,
    stdin: TextIO | None = None,
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,
) -> int:
    """Run phased setup. Returns a process exit code."""
    out = stdout if stdout is not None else sys.stdout
    err = stderr if stderr is not None else sys.stderr
    inn = stdin if stdin is not None else sys.stdin

    try:
        return _run_setup(
            config_dir=config_dir,
            yes=yes,
            force=force,
            skip_provider=skip_provider,
            skip_doctor=skip_doctor,
            stdin=inn,
            stdout=out,
            stderr=err,
        )
    except KeyboardInterrupt:
        err.write("\nsetup cancelled\n")
        return 130


def _run_setup(
    *,
    config_dir: str | Path | None,
    yes: bool,
    force: bool,
    skip_provider: bool,
    skip_doctor: bool,
    stdin: TextIO,
    stdout: TextIO,
    stderr: TextIO,
) -> int:
    target = resolve_config_dir(config_dir)
    paths = config_paths(target)
    soothe_home = Path(SOOTHE_HOME).expanduser()

    stdout.write(f"Config directory: {target}\n")
    stdout.write("\n[1/4] Scaffolding config files...\n")
    scaffold_configs(target, force=force, stdout=stdout)

    if yes or skip_provider:
        stdout.write("\n[2/4] Provider configuration: skipped")
        if yes:
            stdout.write(" (--yes)")
        elif skip_provider:
            stdout.write(" (--skip-provider)")
        stdout.write("\n")
        if yes:
            merged = merge_provider_from_env(paths["nano"])
            if merged is not None:
                stdout.write("  merged provider from environment API keys\n")
    else:
        stdout.write("\n[2/4] Provider configuration...\n")
        try:
            run_provider_wizard(
                paths["nano"],
                soothe_home=soothe_home,
                stdin=stdin,
                stdout=stdout,
                stderr=stderr,
            )
        except ProviderSetupSkippedError:
            stdout.write("  provider step skipped\n")
        except ProviderSetupCancelledError as exc:
            msg = str(exc) or "setup cancelled"
            stderr.write(f"{msg}\n")
            # Scaffold already written — fault-tolerant: leave files, non-zero exit.
            stderr.write("Scaffolded configs were kept. Re-run `soothed setup` to finish.\n")
            return 1

    stdout.write("\n[3/4] Validating configs...\n")
    ok = validate_configs(
        nano_path=paths["nano"],
        soothe_path=paths["soothe"],
        daemon_path=paths["daemon"],
        stdout=stdout,
        stderr=stderr,
    )
    if not ok:
        stderr.write("Config validation failed. Fix the YAML and re-run setup.\n")
        return 1

    if skip_doctor or yes:
        stdout.write("\n[4/4] Provider health check: skipped\n")
    else:
        stdout.write("\n[4/4] Provider health check...\n")
        try:
            asyncio.run(
                run_provider_doctor(
                    nano_path=paths["nano"],
                    soothe_path=paths["soothe"],
                    daemon_path=paths["daemon"],
                    stdout=stdout,
                    stderr=stderr,
                )
            )
        except Exception as exc:  # pragma: no cover - defensive
            stderr.write(f"  doctor warning: {exc}\n")

    stdout.write("\nSetup complete.\n")
    stdout.write(f"  nano:   {paths['nano']}\n")
    stdout.write(f"  soothe: {paths['soothe']}\n")
    stdout.write(f"  daemon: {paths['daemon']}\n")
    stdout.write("\nNext steps:\n")
    stdout.write("  soothed start\n")
    stdout.write('  soothe -p "hello"\n')
    return 0
