#!/usr/bin/env python3
"""Detect dead-duplicate public symbols defined in both soothe-nano and host.

IG-678 PR-10: the literal-name boundary ban in
``check_module_import_boundaries.sh`` catches direct host-concept names
(``StrangeLoop``, ``CronConfig``, etc.) but misses the case where nano
defines a public class/function that the **host already defines under the
same name** — a dead stale duplicate. This recurred across IG-678 PR-2
(``DisplayCardStore``), PR-4 (``translate_client_path_to_container`` etc.),
and PR-6 (``ThreadLogger``, ``ConfigWatcher``, ``THREADS_DATA_DIR``). The
host's copy is always the live canonical one (all callers import from the
host); nano's copy is dead.

This checker cross-references public symbol definitions (top-level classes
and ``def`` statements, plus module-level ``NAME = <literal>`` constants)
between ``packages/soothe-nano/src`` and ``packages/soothe/src`` +
``packages/soothe-daemon/src``. To distinguish a genuine *dead* duplicate
from an intentional shared/mirrored symbol, a candidate is flagged only
when it also has **zero import references inside nano** (neither imported
nor called by any nano module other than its own definition file). This is
the caller-graph refinement: a nano symbol the host also defines AND that
nano itself never uses is dead weight.

Exit codes:
    0 — no unexpected duplicates detected.
    1 — unexpected duplicates detected (review + consolidate or allowlist).

Usage::

    python scripts/check_nano_duplicate_symbols.py
"""

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
NANO_SRC = ROOT / "packages" / "soothe-nano" / "src" / "soothe_nano"
HOST_SRC = ROOT / "packages" / "soothe" / "src" / "soothe"
DAEMON_SRC = ROOT / "packages" / "soothe-daemon" / "src" / "soothe_daemon"


def _public_symbols(path: Path) -> set[str]:
    """Return top-level public class/function/constant names defined in ``path``.

    Only top-level (module-scope) definitions are collected — nested classes
    inside functions, locals, and ``_``-prefixed private names are skipped.
    Constants captured via ``NAME = <literal>`` at module scope are included
    only for ``UPPER_SNAKE`` names (to catch e.g. ``THREADS_DATA_DIR``).
    """
    names: set[str] = set()
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (SyntaxError, OSError):
        return names
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and not node.name.startswith("_"):
            names.add(node.name)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and not node.name.startswith(
            "_"
        ):
            names.add(node.name)
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if (
                    isinstance(target, ast.Name)
                    and target.id.isupper()
                    and not target.id.startswith("_")
                ):
                    names.add(target.id)
    return names


def _package_symbols(pkg_root: Path) -> dict[str, list[str]]:
    """Map symbol name → list of defining file paths (relative to pkg_root)."""
    out: list[tuple[str, str]] = []
    for py in sorted(pkg_root.rglob("*.py")):
        rel = py.relative_to(pkg_root)
        for name in _public_symbols(py):
            out.append((name, str(rel)))
    result: dict[str, list[str]] = {}
    for name, rel in out:
        result.setdefault(name, []).append(rel)
    return result


# Intentionally-shared names that are NOT dead duplicates even though they
# pass the zero-in-nano-imports filter. These fall into a few documented
# categories — extend ONLY with a documented reason when the caller-graph
# filter produces a new false positive.
_ALLOWED_DUPLICATES: dict[str, str] = {
    # --- Shared event/wire constants (nano defines the namespace; host
    #     re-declares for its own event catalog merge). Not a leak.
    "MCP_LIST_CHANGED": "shared event constant — nano namespace; host re-declares for catalog",
    "MCP_TOOL_TIMEOUT": "shared event constant — nano namespace; host re-declares for catalog",
    "PLUGIN_FAILED": "shared event constant — nano namespace; host re-declares for catalog",
    "PLUGIN_LOADED": "shared event constant — nano namespace; host re-declares for catalog",
    "PLUGIN_UNLOADED": "shared event constant — nano namespace; host re-declares for catalog",
    "REPLAY_COMPLETE": "shared event constant — nano namespace; host re-declares for catalog",
    "SKILL_BODY_LOADED": "shared event constant — nano namespace; host re-declares for catalog",
    # --- Shared execution constants (nano-owned limits; host re-declares).
    "MAX_EXECUTE_TIMEOUT": "shared execution constant — nano-owned limit; host re-declares",
    # --- Split-config default factories / logging view (settings.py mirrors).
    "SootheConfigLoggingView": "split-config mirror — logging view mirrored per ownership",
    "default_embedding_profile": "split-config default — embedding_profile is nano-owned; host mirrors",
    "default_router_profiles": "split-config default — router_profiles is nano-owned; host mirrors",
    "default_vector_store_router": "split-config default — vector_store_router is nano-owned; host mirrors",
    "default_vector_stores": "split-config default — vector_stores is nano-owned; host mirrors",
    # --- Postgres-provisioning helpers (nano-owned; host re-declares in its
    #     own persistence for host-internal callers).
    "postgres_admin_dsn": "nano-owned provisioning helper; host re-declares for host callers",
    "postgres_target_dsn": "nano-owned provisioning helper; host re-declares for host callers",
    "required_postgres_database_keys": "nano-owned provisioning helper; host re-declares for host callers",
    "reset_provision_cache_for_tests": "nano-owned provisioning helper; host re-declares for host callers",
    "uses_postgresql_persistence": "nano-owned provisioning helper; host/daemon re-declares for their callers",
    "validate_database_name": "nano-owned provisioning helper; host re-declares for host callers",
    # --- Prompt helpers (nano-owned; host mirrors for its own prompt assembly).
    "build_shared_environment_workspace_prefix": "nano-owned prompt helper; host mirrors",
    "current_timestamp_iso": "nano-owned prompt helper; host mirrors",
    "uses_builtin_agent_system_prompt": "nano-owned prompt helper; host mirrors",
}


def _nano_usage_outside_defining_files() -> dict[str, set[str]]:
    """Map symbol name → set of nano files (relative paths) that reference it.

    A symbol's own ``class Foo:`` / ``def foo()`` / ``FOO = …`` line contains
    its name as a bare word, so a naive text scan would mark every defined
    symbol as "used". To avoid that, for each name we collect the set of nano
    files in which the name appears as a bare word, and the caller treats a
    name as *used in nano* only if it appears in some file OTHER than its own
    defining file(s).
    """
    usage: dict[str, set[str]] = {}
    for py in NANO_SRC.rglob("*.py"):
        rel = str(py.relative_to(NANO_SRC))
        try:
            text = py.read_text(encoding="utf-8")
        except OSError:
            continue
        for match in re.finditer(r"\b([A-Za-z_][A-Za-z0-9_]*)\b", text):
            usage.setdefault(match.group(1), set()).add(rel)
    return usage


def _collect_dead(
    nano: dict[str, list[str]],
    host: dict[str, list[str]],
    nano_usage: dict[str, set[str]],
) -> list[tuple[str, list[str], list[str]]]:
    """Return nano symbols also defined in host AND unused inside nano.

    "Unused" = the name appears as a bare word in nano ONLY in its own
    defining file(s) — no other nano module references it.
    """
    out: list[tuple[str, list[str], list[str]]] = []
    for name, nano_files in sorted(nano.items()):
        if name not in host:
            continue
        defining = set(nano_files)
        referencing = nano_usage.get(name, set())
        external_refs = referencing - defining
        if external_refs:
            continue  # referenced by some other nano module — not dead
        out.append((name, nano_files, host[name]))
    return out


def main() -> int:
    nano = _package_symbols(NANO_SRC)
    host = _package_symbols(HOST_SRC)
    daemon = _package_symbols(DAEMON_SRC)
    host_side: dict[str, list[str]] = {}
    for name, files in host.items():
        host_side.setdefault(name, []).extend(f"soothe/{f}" for f in files)
    for name, files in daemon.items():
        host_side.setdefault(name, []).extend(f"soothe_daemon/{f}" for f in files)

    nano_usage = _nano_usage_outside_defining_files()
    dead = _collect_dead(nano, host_side, nano_usage)
    unexpected = [(n, nf, hf) for (n, nf, hf) in dead if n not in _ALLOWED_DUPLICATES]

    if not unexpected:
        print("OK: no dead-duplicate nano↔host public symbols detected.")
        return 0

    print("FAILED: nano defines public symbols also defined in host/daemon,")
    print("  with zero in-nano references — likely dead stale duplicates.")
    print("  The host copy is usually canonical. Consolidate or, if genuinely")
    print("  shared, add to _ALLOWED_DUPLICATES with a documented reason.")
    print()
    for name, nano_files, host_files in unexpected:
        print(f"  {name}")
        print(f"    nano: {', '.join(nano_files)}")
        print(f"    host: {', '.join(host_files)}")
    print()
    print(f"  ({len(unexpected)} dead duplicate name(s))")
    return 1


if __name__ == "__main__":
    sys.exit(main())
