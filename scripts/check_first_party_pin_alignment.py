#!/usr/bin/env python3
"""Ensure soothe and soothe-daemon declare compatible first-party pins.

The Docker image installs ``soothe==VERSION`` and ``soothe-daemon==VERSION``
together from PyPI. If those packages pin disjoint ranges for a shared
dependency (e.g. soothe-nano), the image build fails at resolve time.

This gate compares declared ranges for shared first-party packages and fails
when their SpecifierSets have an empty intersection.
"""

from __future__ import annotations

import re
import sys
import tomllib
from pathlib import Path

from packaging.requirements import Requirement
from packaging.specifiers import SpecifierSet
from packaging.version import Version

ROOT = Path(__file__).resolve().parents[1]

# Packages that both soothe and soothe-daemon may declare; ranges must overlap.
SHARED_FIRST_PARTY = ("soothe-nano", "soothe-sdk")

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


def main() -> int:
    soothe = _load_deps("packages/soothe/pyproject.toml")
    daemon = _load_deps("packages/soothe-daemon/pyproject.toml")
    errors: list[str] = []

    for name in SHARED_FIRST_PARTY:
        if name not in soothe:
            errors.append(f"soothe is missing dependency on {name}")
            continue
        if name not in daemon:
            errors.append(f"soothe-daemon is missing dependency on {name}")
            continue
        a = soothe[name].specifier
        b = daemon[name].specifier
        if not _ranges_intersect(a, b):
            errors.append(
                f"{name}: soothe requires {_normalize_spec(a)} but "
                f"soothe-daemon requires {_normalize_spec(b)} "
                f"(empty intersection — Docker/PyPI co-install will fail)"
            )

    # Daemon must depend on soothe with a floor that can satisfy soothe's own
    # first-party pins (soothe-nano floor in particular).
    soothe_req = daemon.get("soothe")
    if soothe_req is None:
        errors.append("soothe-daemon is missing dependency on soothe")
    else:
        version_path = ROOT / "VERSION"
        version = version_path.read_text().strip()
        if not re.fullmatch(r"\d+\.\d+\.\d+", version):
            errors.append(f"VERSION looks invalid: {version!r}")
        elif Version(version) not in soothe_req.specifier:
            errors.append(
                f"soothe-daemon soothe pin {_normalize_spec(soothe_req.specifier)} "
                f"does not admit current VERSION {version}"
            )

    if errors:
        print("FAILED: first-party pin alignment")
        for err in errors:
            print(f"  - {err}")
        print(
            "\nAlign pins in packages/soothe/pyproject.toml and "
            "packages/soothe-daemon/pyproject.toml before release."
        )
        return 1

    print("OK: soothe and soothe-daemon first-party pins intersect")
    for name in SHARED_FIRST_PARTY:
        print(
            f"  {name}: soothe={_normalize_spec(soothe[name].specifier)} "
            f"daemon={_normalize_spec(daemon[name].specifier)}"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
