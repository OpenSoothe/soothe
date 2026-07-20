#!/usr/bin/env python3
"""IG-668 Phase B–C: bulk-copy CoreAgent cluster into soothe_nano and rewrite imports."""

from __future__ import annotations

import re
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "packages" / "soothe" / "src" / "soothe"
DST = ROOT / "packages" / "soothe-nano" / "src" / "soothe_nano"

# (src relative to SRC, dst relative to DST)
COPY_DIRS: list[tuple[str, str]] = [
    ("toolkits", "toolkits"),
    ("middleware", "middleware"),
    ("skills", "skills"),
    ("mcp", "mcp"),
    ("plugin", "plugin"),
    ("config", "config"),
    ("protocols", "protocols"),
    ("utils", "utils"),
    ("logging", "logging"),
    ("subagents", "subagents"),
    ("foundation/filesystem", "filesystem"),
    ("foundation/security", "security"),
    ("foundation/workspace", "workspace"),
    ("foundation/events", "events"),
]

COPY_FILES: list[tuple[str, str]] = [
    ("foundation/coreagent/coding/builder.py", "agent/builder.py"),
    ("foundation/coreagent/coding/factory.py", "agent/factory.py"),
    ("runner/resolver/_resolver_tools.py", "resolve/_resolver_tools.py"),
    ("runner/resolver/_lazy_subagent.py", "resolve/_lazy_subagent.py"),
    ("runner/resolver/_tool_cache.py", "resolve/_tool_cache.py"),
]

# Longest-prefix first for import rewrites
IMPORT_REWRITES: list[tuple[str, str]] = [
    ("soothe.foundation.filesystem", "soothe_nano.filesystem"),
    ("soothe.foundation.security", "soothe_nano.security"),
    ("soothe.foundation.workspace", "soothe_nano.workspace"),
    ("soothe.foundation.events", "soothe_nano.events"),
    ("soothe.foundation.coreagent.coding", "soothe_nano.agent"),
    ("soothe.foundation.coreagent", "soothe_nano.agent"),
    ("soothe.runner.resolver", "soothe_nano.resolve"),
    ("soothe.toolkits", "soothe_nano.toolkits"),
    ("soothe.middleware", "soothe_nano.middleware"),
    ("soothe.skills", "soothe_nano.skills"),
    ("soothe.mcp", "soothe_nano.mcp"),
    ("soothe.plugin", "soothe_nano.plugin"),
    ("soothe.config", "soothe_nano.config"),
    ("soothe.protocols", "soothe_nano.protocols"),
    ("soothe.utils", "soothe_nano.utils"),
    ("soothe.logging", "soothe_nano.logging"),
    ("soothe.subagents", "soothe_nano.subagents"),
]


def copy_tree(src: Path, dst: Path) -> None:
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(
        src,
        dst,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".pytest_cache", "*.egg-info"),
    )


def rewrite_text(text: str) -> str:
    # from soothe.X / import soothe.X
    for old, new in IMPORT_REWRITES:
        text = text.replace(f"from {old}", f"from {new}")
        text = text.replace(f"import {old}", f"import {new}")
    return text


def rewrite_file(path: Path) -> bool:
    if path.suffix != ".py":
        return False
    original = path.read_text(encoding="utf-8")
    updated = rewrite_text(original)
    if updated != original:
        path.write_text(updated, encoding="utf-8")
        return True
    return False


def main() -> None:
    changed = 0
    for src_rel, dst_rel in COPY_DIRS:
        src = SRC / src_rel
        dst = DST / dst_rel
        print(f"copy {src_rel} -> {dst_rel}")
        copy_tree(src, dst)

    for src_rel, dst_rel in COPY_FILES:
        src = SRC / src_rel
        dst = DST / dst_rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        print(f"copy file {src_rel} -> {dst_rel}")
        shutil.copy2(src, dst)

    # Preserve Phase A agent modules that already exist (core_agent, lazy, etc.)
    # builder/factory were overwritten/copied; keep execute_stream & subagent_catalog.

    for path in DST.rglob("*.py"):
        if rewrite_file(path):
            changed += 1
    print(f"rewrote imports in {changed} files")

    # Remaining soothe imports inside nano (should be empty or backends/sloop/etc.)
    leftover: list[str] = []
    pat = re.compile(r"^\s*(from|import)\s+soothe(\.|$|\s)", re.M)
    for path in DST.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        if pat.search(text):
            # allow soothe_nano / soothe_sdk / soothe_deepagents already filtered by pattern
            for line in text.splitlines():
                if re.match(r"^\s*(from|import)\s+soothe(\.|$|\s)", line):
                    if not re.match(r"^\s*(from|import)\s+soothe_(nano|sdk|deepagents)", line):
                        leftover.append(f"{path.relative_to(DST)}: {line.strip()}")
    print(f"leftover soothe imports: {len(leftover)}")
    for line in leftover[:80]:
        print(f"  {line}")


if __name__ == "__main__":
    main()
