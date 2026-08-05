"""LoopRail catalog loader — resolve rail YAML by id with tier precedence."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from soothe.rails.builtins import get_rails_paths

# CE built-ins referenced by rail ``then:`` (LoopRail design draft §5).
CE_RAIL_BUILTINS: frozenset[str] = frozenset(
    {
        "decompose_parallel",
        "plan_and_implement",
        "plan_milestones",
        "spawn_wave_makers",
        "spawn_integrate",
        "commit_milestone",
        "spawn_feedback_cycle",
        "review",
        "qa_verify",
        "retry_branch",
        "retry_maker",
        "merge_branches",
        "pause_for_user",
        "complete_job",
    }
)


class RailCatalogError(ValueError):
    """Raised when a rail document is missing or invalid."""


# --- Integrity verification (SC-01 hardening) ---------------------------

_BUILTIN_RAIL_HASHES: dict[str, str] = {
    "bugfix": "pending",
    "feature-dev": "pending",
    "hotfix": "pending",
    "maker-checker": "pending",
    "migration": "pending",
    "pr-review": "pending",
    "spike": "pending",
    "greenfield-system": "pending",
}


def compute_rail_hash(text: str) -> str:
    """Return the SHA-256 integrity hash for raw rail YAML text."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _is_safe_rail_id(rail_id: str) -> bool:
    """Reject path traversal characters in rail ids."""
    if not rail_id or not rail_id.strip():
        return False
    if "/" in rail_id or "\\" in rail_id or ".." in rail_id:
        return False
    return True


@dataclass(frozen=True)
class RailDefinition:
    """Parsed LoopRail document.

    Args:
        id: Rail identifier (must match filename stem).
        version: Semver string from the document.
        summary: NL overview for auto-pick and docs.
        applies_when: NL condition for rail selection.
        conditions: Named NL guards.
        flow: NL-first event hooks (list of mappings).
        rules: Explicit rule list (list of mappings).
        source_path: Absolute path to the YAML file that won resolution.
    """

    id: str
    version: str
    summary: str
    applies_when: str
    conditions: dict[str, str] = field(default_factory=dict)
    flow: list[dict[str, Any]] = field(default_factory=list)
    rules: list[dict[str, Any]] = field(default_factory=list)
    source_path: Path | None = None
    integrity_hash: str = ""


def _require_str(data: dict[str, Any], key: str, *, path: Path) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        raise RailCatalogError(f"{path}: missing or empty required field '{key}'")
    return value.strip()


def _normalize_conditions(raw: Any, *, path: Path) -> dict[str, str]:
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise RailCatalogError(f"{path}: 'conditions' must be a mapping")
    out: dict[str, str] = {}
    for name, text in raw.items():
        if not isinstance(name, str) or not isinstance(text, str):
            raise RailCatalogError(f"{path}: conditions entries must be str → str")
        out[name] = text.strip()
    return out


def _normalize_list_of_maps(raw: Any, *, field_name: str, path: Path) -> list[dict[str, Any]]:
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise RailCatalogError(f"{path}: '{field_name}' must be a list")
    out: list[dict[str, Any]] = []
    for i, item in enumerate(raw):
        if not isinstance(item, dict):
            raise RailCatalogError(f"{path}: '{field_name}[{i}]' must be a mapping")
        out.append(_normalize_flow_entry_keys(dict(item)))
    return out


def _normalize_flow_entry_keys(entry: dict[str, Any]) -> dict[str, Any]:
    """Normalize flow/rule keys.

    Canonical trigger field is ``event``. Legacy ``on`` (and YAML 1.1 boolean
    ``True`` from bare ``on:``) is rewritten to ``event``.
    """
    fixed: dict[str, Any] = {}
    for key, value in entry.items():
        if key is True or key == "on":
            # Prefer an explicit ``event`` if both somehow appear.
            fixed.setdefault("event", value)
            continue
        if key is False:
            fixed["off"] = value
            continue
        fixed[key] = value
    return fixed


def _collect_then_verbs(flow: list[dict[str, Any]], rules: list[dict[str, Any]]) -> list[str]:
    verbs: list[str] = []
    for entry in flow:
        then = entry.get("then")
        if isinstance(then, str):
            verbs.append(then)
        elif isinstance(then, list):
            verbs.extend(v for v in then if isinstance(v, str))
    for entry in rules:
        then = entry.get("then")
        if isinstance(then, str):
            verbs.append(then)
        elif isinstance(then, list):
            verbs.extend(v for v in then if isinstance(v, str))
    return verbs


def load_rail_file(path: Path) -> RailDefinition:
    """Parse and validate a single rail YAML file.

    Args:
        path: Path to ``<rail-id>.yml``.

    Returns:
        Validated ``RailDefinition``.

    Raises:
        RailCatalogError: On parse or schema errors.
    """
    path = path.resolve()
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise RailCatalogError(f"cannot read rail file: {path}") from exc

    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise RailCatalogError(f"{path}: invalid YAML: {exc}") from exc

    if not isinstance(data, dict):
        raise RailCatalogError(f"{path}: rail document must be a mapping")

    rail_id = _require_str(data, "id", path=path)
    if path.stem != rail_id:
        raise RailCatalogError(f"{path}: id '{rail_id}' must match filename stem '{path.stem}'")

    if not _is_safe_rail_id(rail_id):
        raise RailCatalogError(f"{path}: rail id '{rail_id}' contains path traversal characters")

    version = _require_str(data, "version", path=path)
    summary = _require_str(data, "summary", path=path)
    applies_when = _require_str(data, "applies_when", path=path)
    conditions = _normalize_conditions(data.get("conditions"), path=path)
    flow = _normalize_list_of_maps(data.get("flow"), field_name="flow", path=path)
    rules = _normalize_list_of_maps(data.get("rules"), field_name="rules", path=path)

    if not flow and not rules:
        raise RailCatalogError(f"{path}: rail must define 'flow' and/or 'rules'")

    unknown = sorted(set(_collect_then_verbs(flow, rules)) - CE_RAIL_BUILTINS)
    if unknown:
        raise RailCatalogError(
            f"{path}: unknown then: verb(s) {unknown}; allowed: {sorted(CE_RAIL_BUILTINS)}"
        )

    return RailDefinition(
        id=rail_id,
        version=version,
        summary=summary,
        applies_when=applies_when,
        conditions=conditions,
        flow=flow,
        rules=rules,
        source_path=path,
        integrity_hash=compute_rail_hash(text),
    )


class LoopRailCatalog:
    """Three-tier rail catalog with last-wins id resolution."""

    def __init__(self, workspace: str | None = None) -> None:
        """Bind catalog roots for a workspace (or daemon-wide only).

        Args:
            workspace: Optional project workspace for ``.soothe/rails/``.
        """
        self._workspace = workspace

    def roots(self) -> list[Path]:
        """Return existing rail directories in precedence order (low → high)."""
        return get_rails_paths(self._workspace)

    def list_ids(self) -> list[str]:
        """Return sorted rail ids after last-wins merge across tiers."""
        return sorted(self._index().keys())

    def resolve(self, rail_id: str) -> RailDefinition:
        """Load a rail by id; higher-precedence tiers override lower ones.

        Args:
            rail_id: Rail identifier (filename stem / ``id`` field).

        Returns:
            Parsed ``RailDefinition`` from the winning tier.

        Raises:
            RailCatalogError: If the rail is not found or fails validation.
        """
        if not _is_safe_rail_id(rail_id):
            raise RailCatalogError(f"rail id '{rail_id}' contains path traversal characters")
        index = self._index()
        path = index.get(rail_id)
        if path is None:
            known = ", ".join(sorted(index)) or "(none)"
            raise RailCatalogError(f"rail not found: '{rail_id}' (known: {known})")
        return load_rail_file(path)

    def verify_integrity(self, rail_id: str, expected_hash: str) -> bool:
        """Verify a rail's SHA-256 integrity hash matches the expected value.

        Used to detect rail YAML tampering (SC-01 hardening). The expected
        hash should be recorded at deployment time from a known-good baseline.

        Args:
            rail_id: Rail identifier to verify.
            expected_hash: Known-good SHA-256 hex digest.

        Returns:
            True if the computed hash matches.

        Raises:
            RailCatalogError: If the rail cannot be resolved.
        """
        rail = self.resolve(rail_id)
        return rail.integrity_hash == expected_hash

    def load_all(self) -> dict[str, RailDefinition]:
        """Resolve every rail id in the merged catalog.

        Returns:
            Mapping of rail id → definition.
        """
        return {rail_id: load_rail_file(path) for rail_id, path in self._index().items()}

    def _index(self) -> dict[str, Path]:
        """Build last-wins map of rail_id → YAML path (skips ``drafts/``)."""
        by_id: dict[str, Path] = {}
        for root in self.roots():
            for path in sorted(root.glob("*.yml")):
                if path.parent.name == "drafts":
                    continue
                by_id[path.stem] = path.resolve()
        return by_id
