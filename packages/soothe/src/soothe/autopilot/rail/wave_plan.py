"""Structured wave fan-out plan for LoopRail (IG-699 / IG-700).

LoopRail owns fan-out *contract* (YAML ``fanout.artifact`` / ``require_plan``).
The **LLM** owns fan-out *policy* (module names + width) via a **job-scoped**
artifact under ``jobs_root`` (typically ``$SOOTHE_DATA_DIR/jobs/{job_id}/``).
Autopilot engine only supplies a spawn budget (``max_parallel_goals``).

No rigid default module list for greenfield: missing plan fails closed when
``require_plan`` is true. Project-workspace singletons are not authoritative.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

logger = logging.getLogger(__name__)

# Default relative path under jobs_root (expand ``{job_id}`` at resolve time).
DEFAULT_WAVE_PLAN_ARTIFACT = "{job_id}/wave-plan.json"

_JOB_ID_TOKEN = "{job_id}"
_JSON_OBJECT_RE = re.compile(r"\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}", re.DOTALL)
# Pre-IG-700 workspace singleton — never load; rewrite to job-scoped default.
_LEGACY_WORKSPACE_WAVE_PLAN_ARTIFACTS = frozenset(
    {
        ".soothe/wave-plan.json",
        "wave-plan.json",
    }
)


class WavePlanModule(BaseModel):
    """One independent ownership unit for a maker wave (LLM-authored)."""

    module: str = Field(..., min_length=1, max_length=64)
    description: str | None = None
    priority: int = Field(default=75, ge=0, le=100)
    tags: list[str] = Field(default_factory=list)

    @field_validator("module")
    @classmethod
    def _strip_module(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("module name must be non-empty")
        return cleaned


class WavePlan(BaseModel):
    """Machine contract for LLM-determined ready-DAG width (rail artifact)."""

    wave_modules: list[str] = Field(default_factory=list)
    modules: list[WavePlanModule] = Field(default_factory=list)
    scout_count: int | None = Field(default=None, ge=1, le=32)
    max_waves: int | None = Field(default=None, ge=1, le=32)
    independence: str | None = None
    rationale: str | None = Field(
        default=None,
        description="Optional LLM rationale for this fan-out partition",
    )

    @field_validator("wave_modules")
    @classmethod
    def _strip_names(cls, value: list[str]) -> list[str]:
        out: list[str] = []
        for item in value:
            name = str(item).strip()
            if name:
                out.append(name)
        return out

    def resolved_module_names(self) -> list[str]:
        """Prefer rich ``modules`` entries, else ``wave_modules``."""
        if self.modules:
            return [m.module for m in self.modules]
        return list(self.wave_modules)

    def as_decompose_plan(self) -> list[dict[str, Any]] | None:
        """Map rich modules to ``RailJobState.decompose_plan`` shape."""
        if not self.modules:
            return None
        return [
            {
                "module": m.module,
                "description": m.description or m.module,
                "priority": m.priority,
                "tags": list(m.tags) or ["implementation", "maker"],
                "role": "maker",
            }
            for m in self.modules
        ]


class FanoutResolution(BaseModel):
    """Result of resolving modules for ``spawn_wave_makers``."""

    modules: list[str]
    source: Literal[
        "decompose_plan",
        "wave_modules",
        "wave_plan",
        "missing_plan",
    ]
    clamped_from: int | None = None
    plan: WavePlan | None = None
    detail: str = ""


def expand_wave_plan_artifact(artifact: str, job_id: str) -> str:
    """Expand ``{job_id}`` in an artifact template (safe filesystem segment)."""
    safe = job_id.replace("/", "_").replace("\\", "_").strip()
    if not safe or ".." in safe:
        raise ValueError(f"invalid job_id for wave-plan path: {job_id!r}")
    template = (artifact or DEFAULT_WAVE_PLAN_ARTIFACT).strip().replace("\\", "/")
    if not template:
        template = DEFAULT_WAVE_PLAN_ARTIFACT
    return template.replace(_JOB_ID_TOKEN, safe)


def normalize_wave_plan_artifact(artifact: str | None) -> str:
    """Return a jobs_root-relative template; rewrite pre-IG-700 workspace paths."""
    raw = (artifact or DEFAULT_WAVE_PLAN_ARTIFACT).strip().replace("\\", "/")
    if not raw or raw in _LEGACY_WORKSPACE_WAVE_PLAN_ARTIFACTS:
        return DEFAULT_WAVE_PLAN_ARTIFACT
    return raw


def resolve_wave_plan_path(
    *,
    jobs_root: Path,
    job_id: str,
    artifact: str = DEFAULT_WAVE_PLAN_ARTIFACT,
) -> Path:
    """Absolute path for the job-scoped wave plan under ``jobs_root``.

    Artifact templates are relative to ``jobs_root`` and may include
    ``{job_id}``. Example: ``{job_id}/wave-plan.json`` →
    ``$SOOTHE_DATA_DIR/jobs/{job_id}/wave-plan.json`` when ``jobs_root`` is
    ``$SOOTHE_DATA_DIR/jobs``.
    """
    root = jobs_root.expanduser().resolve()
    expanded = expand_wave_plan_artifact(normalize_wave_plan_artifact(artifact), job_id)
    if expanded.startswith("/") or ".." in expanded.split("/"):
        raise ValueError(f"wave-plan artifact must be relative without '..': {artifact!r}")
    path = (root / expanded).resolve()
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"wave-plan path escapes jobs_root: {path}") from exc
    return path


def load_wave_plan(path: Path) -> WavePlan | None:
    """Load and validate a wave plan JSON file.

    Returns:
        Parsed ``WavePlan``, or None if missing / invalid (never scrapes prose).
    """
    if not path.is_file():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("Invalid wave plan JSON at %s: %s", path, exc)
        return None
    return parse_wave_plan_payload(raw, source=str(path))


def parse_wave_plan_payload(raw: Any, *, source: str = "payload") -> WavePlan | None:
    """Validate a dict (or JSON string) as ``WavePlan``.

    Structured ingest only — does not scrape free-form prose for module names.
    """
    if isinstance(raw, str):
        text = raw.strip()
        if not text:
            return None
        try:
            raw = json.loads(text)
        except json.JSONDecodeError:
            return None
    if not isinstance(raw, dict):
        return None
    try:
        plan = WavePlan.model_validate(raw)
    except Exception as exc:
        logger.warning("Wave plan schema validation failed (%s): %s", source, exc)
        return None
    if not plan.resolved_module_names() and plan.scout_count is None:
        logger.warning("Wave plan (%s) has no modules or scout_count", source)
        return None
    return plan


def parse_wave_plan_from_findings(findings: list[Any] | None) -> WavePlan | None:
    """Extract a WavePlan from structured goal findings (not prose scrapes).

    Accepts a findings entry that is a dict, a JSON object string, or a string
    containing a single JSON object that validates as ``WavePlan``.
    """
    if not findings:
        return None
    for idx, item in enumerate(findings):
        if isinstance(item, dict):
            plan = parse_wave_plan_payload(item, source=f"findings[{idx}]")
            if plan is not None:
                return plan
            continue
        if not isinstance(item, str):
            continue
        text = item.strip()
        plan = parse_wave_plan_payload(text, source=f"findings[{idx}]")
        if plan is not None:
            return plan
        # Single embedded JSON object (e.g. "Wave plan:\\n{...}") — still
        # structured JSON, not keyword/module-name heuristics.
        for match in _JSON_OBJECT_RE.finditer(text):
            plan = parse_wave_plan_payload(match.group(0), source=f"findings[{idx}].embed")
            if plan is not None and plan.resolved_module_names():
                return plan
    return None


def dump_wave_plan(plan: WavePlan, path: Path) -> None:
    """Persist a validated plan to ``path`` (creates parents)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(plan.model_dump(mode="json", exclude_none=True), indent=2, sort_keys=True),
        encoding="utf-8",
    )


def clamp_module_list(
    modules: list[str],
    *,
    max_modules: int,
) -> tuple[list[str], int | None]:
    """Dedupe (order-preserving) and clamp length to engine spawn budget.

    Returns:
        (modules, clamped_from) where ``clamped_from`` is the pre-clamp length
        when truncated, else None.
    """
    seen: set[str] = set()
    unique: list[str] = []
    for name in modules:
        key = name.strip()
        if not key or key.lower() in seen:
            continue
        seen.add(key.lower())
        unique.append(key)
    cap = max(1, int(max_modules))
    if len(unique) > cap:
        return unique[:cap], len(unique)
    return unique, None


def resolve_fanout_modules(
    *,
    wave_modules: list[str] | None,
    decompose_plan: list[dict[str, Any]] | None,
    plan: WavePlan | None,
    max_modules: int,
    require_plan: bool = True,
) -> FanoutResolution:
    """Resolve maker module names from LLM artifact only (+ engine clamp).

    Precedence (IG-699 / IG-700):
    1. ``decompose_plan`` on rail state (from LLM artifact ingest)
    2. ``wave_modules`` on rail state (from LLM artifact ingest)
    3. In-memory ``WavePlan`` still held by caller
    4. Else ``missing_plan`` — empty modules when ``require_plan`` (fail closed)

    Rigid YAML/code default module lists are intentionally not used.
    """
    source: Literal["decompose_plan", "wave_modules", "wave_plan", "missing_plan"]
    raw: list[str]

    if decompose_plan:
        raw = [
            str(spec.get("module") or spec.get("description") or f"m{i}")
            for i, spec in enumerate(decompose_plan)
        ]
        source = "decompose_plan"
    elif wave_modules:
        raw = list(wave_modules)
        source = "wave_modules"
    elif plan is not None and plan.resolved_module_names():
        raw = plan.resolved_module_names()
        source = "wave_plan"
    else:
        detail = (
            "LLM wave plan required but missing or empty; "
            "architecture must record_wave_plan (or emit structured WavePlan "
            "findings) before makers spawn"
        )
        logger.warning("%s", detail)
        return FanoutResolution(
            modules=[],
            source="missing_plan",
            clamped_from=None,
            plan=None,
            detail=detail,
        )

    clamped, clamped_from = clamp_module_list(raw, max_modules=max_modules)
    if not clamped:
        detail = "wave plan resolved to an empty module list after clamp"
        if require_plan:
            return FanoutResolution(
                modules=[],
                source="missing_plan",
                clamped_from=clamped_from,
                plan=plan if source == "wave_plan" else None,
                detail=detail,
            )
        return FanoutResolution(
            modules=[],
            source="missing_plan",
            clamped_from=clamped_from,
            plan=None,
            detail=detail,
        )

    return FanoutResolution(
        modules=clamped,
        source=source,
        clamped_from=clamped_from,
        plan=plan if source == "wave_plan" else None,
        detail="",
    )


def apply_wave_plan_to_state_fields(plan: WavePlan) -> dict[str, Any]:
    """Derive RailJobState field updates from a validated plan (unclamped)."""
    names = plan.resolved_module_names()
    updates: dict[str, Any] = {
        "wave_modules": names or None,
    }
    decompose = plan.as_decompose_plan()
    if decompose is not None:
        updates["decompose_plan"] = decompose
    if plan.scout_count is not None:
        updates["scout_count"] = plan.scout_count
    if plan.max_waves is not None:
        updates["max_waves"] = plan.max_waves
    return updates


def build_wave_plan(
    *,
    wave_modules: list[str] | None = None,
    modules: list[dict[str, Any] | WavePlanModule] | None = None,
    rationale: str | None = None,
    independence: str | None = None,
    max_waves: int | None = None,
    scout_count: int | None = None,
) -> WavePlan:
    """Build a validated ``WavePlan`` from tool / API arguments."""
    rich: list[WavePlanModule] = []
    if modules:
        for item in modules:
            if isinstance(item, WavePlanModule):
                rich.append(item)
            else:
                rich.append(WavePlanModule.model_validate(item))
    return WavePlan.model_validate(
        {
            "wave_modules": list(wave_modules or []),
            "modules": rich,
            "rationale": rationale,
            "independence": independence,
            "max_waves": max_waves,
            "scout_count": scout_count,
        }
    )
