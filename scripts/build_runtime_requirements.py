"""Build runtime dependency requirements for local daemon Docker image.

Generates dependency lines from package metadata (soothe, daemon) so Docker
can cache dependency installation independently from source code changes.

``soothe-nano`` and ``soothe-deepagents`` are installed from PyPI; their pins
are taken from ``soothe``'s and ``soothe-daemon``'s dependencies.
``soothe``, ``soothe-daemon``, ``soothe-cli``, and ``soothe-sdk`` are installed
from local source with ``--no-deps``.
"""

from __future__ import annotations

import argparse
import re
import tomllib
from pathlib import Path

# Installed from local source (workspace packages) with --no-deps.
SKIP_LOCAL = {
    "soothe",
    "soothe-daemon",
    "soothe-cli",
    "soothe-sdk",
}


def req_name(requirement: str) -> str:
    match = re.match(r"\s*([A-Za-z0-9_.-]+)", requirement or "")
    return match.group(1).lower() if match else ""


def add_reqs(target: list[str], reqs: list[str], *, keep: set[str] | None = None) -> None:
    keep = keep or set()
    for req in reqs or []:
        name = req_name(req)
        if name in SKIP_LOCAL and name not in keep:
            continue
        target.append(req)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--app-root", default="/app")
    parser.add_argument("--include-browser", action="store_true")
    parser.add_argument("--output", default="/tmp/requirements.runtime.txt")
    args = parser.parse_args()

    app_root = Path(args.app_root)
    core = tomllib.loads((app_root / "packages/soothe/pyproject.toml").read_text())
    daemon = tomllib.loads((app_root / "packages/soothe-daemon/pyproject.toml").read_text())

    requirements: list[str] = []
    # Keep first-party PyPI pins (nano / deepagents); skip local soothe/sdk/daemon.
    add_reqs(
        requirements,
        core["project"].get("dependencies", []),
        keep={"soothe-nano", "soothe-deepagents"},
    )
    add_reqs(
        requirements,
        daemon["project"].get("dependencies", []),
        keep={"soothe-nano", "soothe-deepagents"},
    )

    if args.include_browser:
        requirements.append("playwright")

    seen: set[str] = set()
    output_lines: list[str] = []
    for req in requirements:
        key = req.strip()
        if not key or key in seen:
            continue
        seen.add(key)
        output_lines.append(key)

    Path(args.output).write_text("\n".join(output_lines) + "\n")


if __name__ == "__main__":
    main()
