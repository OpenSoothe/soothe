#!/usr/bin/env python3
"""Detect IG-XXX / RFC-XXX references in soothe-nano and soothe-sdk source.

AGENTS.md §7b: ``soothe-nano`` and ``soothe-sdk`` are standalone packages and
must not reference parent-workspace documentation (the monorepo's ``docs/specs/``
RFCs and ``docs/impl/`` IGs) — a standalone nano/sdk consumer does not have
those docs. Docstrings, comments, and ``__init__`` package summaries must read
as self-contained.

This checker scans every ``*.py`` under:
  * ``packages/soothe-nano/src``
  * ``packages/soothe-sdk/src``

and flags any ``IG-NNN`` / ``RFC-NNNN`` reference. The only permitted exception
is a package-level ``__init__.py`` docstring that says "no StrangeLoop" or
"no Autopilot" to mark the package scope — but even those must not carry an
IG/RFC *number*.

Exit codes:
    0 — no IG/RFC references in nano/sdk source.
    1 — references found (remove them; replace with plain-English descriptions).

Usage::

    python scripts/check_nano_docstring_refs.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCAN_PATHS = (
    ROOT / "packages" / "soothe-nano" / "src",
    ROOT / "packages" / "soothe-sdk" / "src",
)

# Match IG-NNN (optionally "Phase N") or RFC-NNNN (3-4 digits).
_REF_RE = re.compile(r"\b(?:IG-\d{3}(?:\s+Phase\s+\d+)?|RFC-\d{3,4})\b")


def _scan(path: Path) -> list[tuple[Path, int, str]]:
    hits: list[tuple[Path, int, str]] = []
    for py in sorted(path.rglob("*.py")):
        try:
            text = py.read_text(encoding="utf-8")
        except OSError:
            continue
        for lineno, line in enumerate(text.splitlines(), start=1):
            for match in _REF_RE.finditer(line):
                hits.append((py, lineno, line.rstrip()))
    return hits


def main() -> int:
    all_hits: list[tuple[str, Path, int, str]] = []
    for scan in SCAN_PATHS:
        if not scan.is_dir():
            continue
        for py, lineno, line in _scan(scan):
            pkg = scan.parent.name
            all_hits.append((pkg, py, lineno, line))

    if not all_hits:
        print("OK: no IG/RFC references in soothe-nano/soothe-sdk source.")
        return 0

    print("FAILED: IG-XXX / RFC-XXX references found in standalone package source.")
    print("  AGENTS.md §7b: soothe-nano and soothe-sdk must not reference")
    print("  parent-workspace IG/RFC docs (a standalone consumer lacks them).")
    print("  Replace the parenthetical with a plain-English description.")
    print()
    by_pkg: dict[str, list[tuple[Path, int, str]]] = {}
    for pkg, py, lineno, line in all_hits:
        by_pkg.setdefault(pkg, []).append((py, lineno, line))
    for pkg, hits in sorted(by_pkg.items()):
        print(f"  [{pkg}] {len(hits)} reference(s):")
        for py, lineno, line in hits:
            rel = py.relative_to(ROOT)
            print(f"    {rel}:{lineno}: {line.strip()}")
        print()
    print(f"  ({len(all_hits)} total reference(s))")
    return 1


if __name__ == "__main__":
    sys.exit(main())
