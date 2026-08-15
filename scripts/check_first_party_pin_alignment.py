#!/usr/bin/env python3
"""Ensure soothe, soothe-autopilot, and soothe-daemon declare compatible pins.

The Docker image installs ``soothe==VERSION``, ``soothe-autopilot==VERSION``,
and ``soothe-daemon==VERSION`` together from PyPI. Daemon and autopilot must
pin ``soothe`` to a range that admits the current monorepo VERSION. When a
package also declares ``soothe-sdk``, that range must intersect soothe's
``soothe-sdk`` pin (empty intersection fails resolve).

Daemon must NOT re-pin ``soothe-nano`` (comes via soothe) or depend on
``soothe-client-python`` at runtime (client sits above the daemon). Autopilot
must not depend on ``soothe-daemon`` / ``soothe-cli`` / ``soothe-client-python``
(it sits above the daemon).
"""

from __future__ import annotations

import os
import re
import sys
import tomllib
from pathlib import Path

from packaging.requirements import Requirement
from packaging.specifiers import SpecifierSet
from packaging.version import Version

ROOT = Path(__file__).resolve().parents[1]

# Optional shared first-party pins: if both packages declare them, ranges must overlap.
SHARED_FIRST_PARTY = ("soothe-sdk",)

# Probe versions covering current and next major floors for intersection tests.
_PROBE_VERSIONS = tuple(
    Version(v)
    for v in (
        "0.9.0",
        "0.9.4",
        "0.9.11",
        "1.0.0",
        "1.0.1",
        "1.0.5",
        "1.1.0",
        "1.9.9",
        "2.0.0",
    )
)

_DAEMON_PYPROJECT = "packages/soothe-daemon/pyproject.toml"
_SOOTHE_PYPROJECT = "packages/soothe/pyproject.toml"
_AUTOPILOT_PYPROJECT = "packages/soothe-autopilot/pyproject.toml"


def _load_deps(rel: str) -> dict[str, Requirement]:
    data = tomllib.loads((ROOT / rel).read_text())
    out: dict[str, Requirement] = {}
    for raw in data["project"].get("dependencies", []):
        req = Requirement(raw)
        out[req.name.lower()] = req
    return out


def _ranges_intersect(a: SpecifierSet, b: SpecifierSet) -> bool:
    """Return True if any probe version satisfies both specifier sets."""
    return any(ver in a and ver in b for ver in _PROBE_VERSIONS)


def _normalize_spec(spec: SpecifierSet) -> str:
    return str(spec) if str(spec) else "(any)"


def _annotate(message: str, file: str | None = None) -> None:
    """Emit a GitHub Actions error annotation when running in CI.

    In local development this is a no-op so console output stays clean.
    In CI the annotation surfaces as an inline comment on the PR diff.
    """
    if os.environ.get("GITHUB_ACTIONS") != "true":
        return
    if file:
        print(f"::error file={file}::{message}")
    else:
        print(f"::error::{message}")


def main() -> int:
    soothe = _load_deps("packages/soothe/pyproject.toml")
    daemon = _load_deps("packages/soothe-daemon/pyproject.toml")
    autopilot = _load_deps("packages/soothe-autopilot/pyproject.toml")
    errors: list[tuple[str, str | None]] = []

    # Daemon must not re-pin nano or depend on the WS client at runtime.
    if "soothe-nano" in daemon:
        errors.append(
            (
                "soothe-daemon must not declare soothe-nano "
                "(it comes transitively via soothe; dual pins drift)",
                _DAEMON_PYPROJECT,
            )
        )
    if "soothe-client-python" in daemon:
        errors.append(
            (
                "soothe-daemon must not declare soothe-client-python in core deps "
                "(client sits above daemon; use soothe-sdk wire + admin_rpc)",
                _DAEMON_PYPROJECT,
            )
        )

    for name in SHARED_FIRST_PARTY:
        if name not in soothe:
            errors.append((f"soothe is missing dependency on {name}", _SOOTHE_PYPROJECT))
            continue
        if name not in daemon:
            errors.append((f"soothe-daemon is missing dependency on {name}", _DAEMON_PYPROJECT))
            continue
        a = soothe[name].specifier
        b = daemon[name].specifier
        if not _ranges_intersect(a, b):
            errors.append(
                (
                    f"{name}: soothe requires {_normalize_spec(a)} but "
                    f"soothe-daemon requires {_normalize_spec(b)} "
                    f"(empty intersection — Docker/PyPI co-install will fail)",
                    _DAEMON_PYPROJECT,
                )
            )

    soothe_req = daemon.get("soothe")
    if soothe_req is None:
        errors.append(("soothe-daemon is missing dependency on soothe", _DAEMON_PYPROJECT))
    else:
        version_path = ROOT / "VERSION"
        version = version_path.read_text().strip()
        if not re.fullmatch(r"\d+\.\d+\.\d+", version):
            errors.append((f"VERSION looks invalid: {version!r}", "VERSION"))
        elif Version(version) not in soothe_req.specifier:
            errors.append(
                (
                    f"soothe-daemon soothe pin {_normalize_spec(soothe_req.specifier)} "
                    f"does not admit current VERSION {version}",
                    _DAEMON_PYPROJECT,
                )
            )

    # Autopilot must not depend on the daemon, CLI, or the WS client (it sits
    # above the daemon, below the host).
    for name in ("soothe-daemon", "soothe-cli", "soothe-client-python"):
        if name in autopilot:
            errors.append(
                (f"soothe-autopilot must not declare {name} in core deps", _AUTOPILOT_PYPROJECT)
            )

    # Autopilot's soothe pin must admit VERSION; its soothe-sdk pin must
    # intersect soothe's (Docker/PyPI co-install).
    ap_soothe_req = autopilot.get("soothe")
    if ap_soothe_req is None:
        errors.append(("soothe-autopilot is missing dependency on soothe", _AUTOPILOT_PYPROJECT))
    else:
        version = (ROOT / "VERSION").read_text().strip()
        if Version(version) not in ap_soothe_req.specifier:
            errors.append(
                (
                    f"soothe-autopilot soothe pin {_normalize_spec(ap_soothe_req.specifier)} "
                    f"does not admit current VERSION {version}",
                    _AUTOPILOT_PYPROJECT,
                )
            )

    if "soothe-sdk" in soothe and "soothe-sdk" in autopilot:
        a = soothe["soothe-sdk"].specifier
        b = autopilot["soothe-sdk"].specifier
        if not _ranges_intersect(a, b):
            errors.append(
                (
                    f"soothe-sdk: soothe requires {_normalize_spec(a)} but "
                    f"soothe-autopilot requires {_normalize_spec(b)} "
                    f"(empty intersection — Docker/PyPI co-install will fail)",
                    _AUTOPILOT_PYPROJECT,
                )
            )

    # Daemon must pin soothe-autopilot to a range admitting the current VERSION.
    daemon_ap_req = daemon.get("soothe-autopilot")
    if daemon_ap_req is None:
        errors.append(
            ("soothe-daemon is missing dependency on soothe-autopilot", _DAEMON_PYPROJECT)
        )
    else:
        version = (ROOT / "VERSION").read_text().strip()
        if Version(version) not in daemon_ap_req.specifier:
            errors.append(
                (
                    f"soothe-daemon soothe-autopilot pin {_normalize_spec(daemon_ap_req.specifier)} "
                    f"does not admit current VERSION {version}",
                    _DAEMON_PYPROJECT,
                )
            )

    if errors:
        print("FAILED: first-party pin alignment")
        for err, fpath in errors:
            print(f"  - {err}")
            _annotate(err, file=fpath)
        print(
            "\nAlign pins in packages/soothe/pyproject.toml, "
            "packages/soothe-autopilot/pyproject.toml, and "
            "packages/soothe-daemon/pyproject.toml before release."
        )
        return 1

    print("OK: soothe, soothe-autopilot, and soothe-daemon first-party pins aligned")
    print(f"  soothe: daemon pin {_normalize_spec(soothe_req.specifier)} admits VERSION")
    print(f"  soothe: autopilot pin {_normalize_spec(ap_soothe_req.specifier)} admits VERSION")
    for name in SHARED_FIRST_PARTY:
        if name in daemon and name in soothe:
            print(
                f"  {name}: soothe={_normalize_spec(soothe[name].specifier)} "
                f"daemon={_normalize_spec(daemon[name].specifier)}"
            )
    return 0


if __name__ == "__main__":
    sys.exit(main())
