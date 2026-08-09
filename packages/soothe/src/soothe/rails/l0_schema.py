"""Catalog-side L0 recipe schema (RFC-231 M3 / IG-717).

Kept under ``soothe.rails`` so catalog validation does not import autopilot.
Runtime execution lives in ``soothe.autopilot.rail.recipe_exec`` (imports
``L0_OPS`` from here).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

# Closed L0 set for IG-717 (single source; recipe_exec re-exports).
L0_OPS: frozenset[str] = frozenset(
    {
        "spawn_goal",
        "wire_deps",
        "gate",
        "bump",
        "pause_job",
        "complete_job",
    }
)


def normalize_do_steps(raw: Any, *, path: Path, verb: str) -> list[dict[str, Any]]:
    """Validate and return a ``do:`` list for catalog loading."""
    from soothe.rails.catalog import RailCatalogError

    if not isinstance(raw, list) or not raw:
        raise RailCatalogError(f"{path}: verbs.{verb}.do must be a non-empty list")
    out: list[dict[str, Any]] = []
    for i, item in enumerate(raw):
        if not isinstance(item, dict) or len(item) != 1:
            raise RailCatalogError(f"{path}: verbs.{verb}.do[{i}] must be a single-key mapping")
        op, spec = next(iter(item.items()))
        if not isinstance(op, str) or op not in L0_OPS:
            raise RailCatalogError(
                f"{path}: verbs.{verb}.do[{i}] unknown L0 op {op!r}; allowed: {sorted(L0_OPS)}"
            )
        if op == "spawn_goal":
            if not isinstance(spec, dict):
                raise RailCatalogError(f"{path}: verbs.{verb}.do[{i}].spawn_goal must be a mapping")
            brief = spec.get("brief")
            if not isinstance(brief, str) or not brief.strip():
                raise RailCatalogError(f"{path}: verbs.{verb}.do[{i}].spawn_goal.brief required")
            if "tags" in spec and spec["tags"] is not None:
                if not isinstance(spec["tags"], list) or not all(
                    isinstance(t, str) for t in spec["tags"]
                ):
                    raise RailCatalogError(
                        f"{path}: verbs.{verb}.do[{i}].spawn_goal.tags must be list[str]"
                    )
            if "intake_scope" in spec and spec["intake_scope"] is not None:
                scope = spec["intake_scope"]
                if not isinstance(scope, str) or scope.strip().lower() not in {
                    "trivial",
                    "simple",
                    "complex",
                }:
                    raise RailCatalogError(
                        f"{path}: verbs.{verb}.do[{i}].spawn_goal.intake_scope "
                        "must be trivial|simple|complex"
                    )
        elif op == "bump":
            if isinstance(spec, str):
                if spec.strip() not in {"feedback_round", "wave_index"}:
                    raise RailCatalogError(f"{path}: verbs.{verb}.do[{i}].bump unsupported counter")
            elif isinstance(spec, dict):
                c = str(spec.get("counter") or "").strip()
                if c not in {"feedback_round", "wave_index"}:
                    raise RailCatalogError(f"{path}: verbs.{verb}.do[{i}].bump unsupported counter")
            else:
                raise RailCatalogError(f"{path}: verbs.{verb}.do[{i}].bump must be str or mapping")
        elif op == "gate" and spec is not None and not isinstance(spec, dict):
            raise RailCatalogError(f"{path}: verbs.{verb}.do[{i}].gate must be a mapping")
        elif op == "wire_deps":
            if not isinstance(spec, dict):
                raise RailCatalogError(f"{path}: verbs.{verb}.do[{i}].wire_deps must be a mapping")
        out.append({op: spec})
    return out
