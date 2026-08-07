"""Structured wave fan-out plan for LoopRail (IG-718).

LoopRail owns fan-out *contract* (YAML ``fanout.artifact`` / ``require_plan``).
The **LLM** owns fan-out *policy* (slice ids + width) via a **job-scoped**
artifact under ``jobs_root`` (typically ``$SOOTHE_DATA_DIR/jobs/{job_id}/``).
Autopilot engine only supplies a spawn budget (``max_parallel_goals``).

A **slice** is an independent parallel ownership unit (feature, task, package,
migration stage, …). Missing plan fails closed when ``require_plan`` is true.
Project-workspace files are never authoritative.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

logger = logging.getLogger(__name__)

DEFAULT_WAVE_PLAN_ARTIFACT = "{job_id}/wave-plan.json"

_JOB_ID_TOKEN = "{job_id}"
_LEGACY_WORKSPACE_WAVE_PLAN_ARTIFACTS = frozenset(
    {
        ".soothe/wave-plan.json",
        "wave-plan.json",
        "docs/wave-plan.json",
    }
)

# Hard cut: removed pre-Slice fan-out wire keys (no dual-read).
_REMOVED_WIRE_KEYS = frozenset({"wave_modules", "modules", "module"})


class WavePlanSlice(BaseModel):
    """One independent slice for a maker wave (LLM-authored)."""

    slice: str = Field(..., min_length=1, max_length=64)
    description: str | None = None
    priority: int = Field(default=75, ge=0, le=100)
    tags: list[str] = Field(default_factory=list)

    @field_validator("slice")
    @classmethod
    def _strip_slice(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("slice id must be non-empty")
        return cleaned


class WavePlan(BaseModel):
    """Machine contract for LLM-determined ready-DAG width (rail artifact)."""

    wave_slices: list[str] = Field(default_factory=list)
    slices: list[WavePlanSlice] = Field(default_factory=list)
    scout_count: int | None = Field(default=None, ge=1, le=32)
    max_waves: int | None = Field(default=None, ge=1, le=32)
    independence: str | None = None
    rationale: str | None = Field(
        default=None,
        description="Optional LLM rationale for this fan-out partition",
    )

    @field_validator("wave_slices")
    @classmethod
    def _strip_names(cls, value: list[str]) -> list[str]:
        out: list[str] = []
        for item in value:
            name = str(item).strip()
            if name:
                out.append(name)
        return out

    def resolved_slice_ids(self) -> list[str]:
        """Prefer rich ``slices`` entries, else ``wave_slices``."""
        if self.slices:
            return [s.slice for s in self.slices]
        return list(self.wave_slices)

    def as_decompose_plan(self) -> list[dict[str, Any]] | None:
        """Map rich slices to ``RailJobState.decompose_plan`` shape."""
        if not self.slices:
            return None
        return [
            {
                "slice": s.slice,
                "description": s.description or s.slice,
                "priority": s.priority,
                "tags": list(s.tags) or ["implementation", "maker"],
                "role": "maker",
            }
            for s in self.slices
        ]


class FanoutResolution(BaseModel):
    """Result of resolving slices for ``spawn_wave_makers``."""

    slices: list[str]
    source: Literal[
        "decompose_plan",
        "wave_slices",
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
    """Return a jobs_root-relative template; rewrite legacy workspace paths."""
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
    """Absolute path for the job-scoped wave plan under ``jobs_root``."""
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
    """Load and validate a wave plan JSON file."""
    if not path.is_file():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("Invalid wave plan JSON at %s: %s", path, exc)
        return None
    return parse_wave_plan_payload(raw, source=str(path))


def _reject_removed_wire_keys(raw: dict[str, Any], *, source: str) -> bool:
    """Return True if payload uses removed pre-Slice fan-out keys."""
    found = sorted(k for k in raw if k in _REMOVED_WIRE_KEYS)
    if not found:
        nested = raw.get("slices")
        if isinstance(nested, list):
            for item in nested:
                if isinstance(item, dict) and "module" in item:
                    found = ["slices[].module"]
                    break
    if found:
        logger.warning(
            "Wave plan (%s) uses removed keys %s; use wave_slices / slices / slice",
            source,
            found,
        )
        return True
    return False


def parse_wave_plan_payload(raw: Any, *, source: str = "payload") -> WavePlan | None:
    """Validate a dict (or JSON string) as ``WavePlan`` (slice schema only)."""
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
    if _reject_removed_wire_keys(raw, source=source):
        return None
    try:
        plan = WavePlan.model_validate(raw)
    except Exception as exc:
        logger.warning("Wave plan schema validation failed (%s): %s", source, exc)
        return None
    if not plan.resolved_slice_ids() and plan.scout_count is None:
        logger.warning("Wave plan (%s) has no slices or scout_count", source)
        return None
    return plan


def iter_embedded_json_objects(text: str) -> list[Any]:
    """Yield top-level JSON values decoded from ``text`` via ``raw_decode``."""
    if not text or not text.strip():
        return []
    decoder = json.JSONDecoder()
    out: list[Any] = []
    idx = 0
    n = len(text)
    while idx < n:
        start_obj = text.find("{", idx)
        start_arr = text.find("[", idx)
        if start_obj < 0 and start_arr < 0:
            break
        if start_obj < 0:
            start = start_arr
        elif start_arr < 0:
            start = start_obj
        else:
            start = min(start_obj, start_arr)
        try:
            obj, end = decoder.raw_decode(text, start)
        except json.JSONDecodeError:
            idx = start + 1
            continue
        out.append(obj)
        idx = end
    return out


def parse_wave_plan_from_findings(findings: list[Any] | None) -> WavePlan | None:
    """Extract a WavePlan from structured goal findings (not prose scrapes)."""
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
        for embed_i, obj in enumerate(iter_embedded_json_objects(text)):
            plan = parse_wave_plan_payload(obj, source=f"findings[{idx}].embed[{embed_i}]")
            if plan is not None and plan.resolved_slice_ids():
                return plan
    return None


def dump_wave_plan(plan: WavePlan, path: Path) -> None:
    """Persist a validated plan to ``path`` (creates parents)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(plan.model_dump(mode="json", exclude_none=True), indent=2, sort_keys=True),
        encoding="utf-8",
    )


def clamp_slice_list(
    slices: list[str],
    *,
    max_slices: int,
) -> tuple[list[str], int | None]:
    """Dedupe (order-preserving) and clamp length to engine spawn budget."""
    seen: set[str] = set()
    unique: list[str] = []
    for name in slices:
        key = name.strip()
        if not key or key.lower() in seen:
            continue
        seen.add(key.lower())
        unique.append(key)
    cap = max(1, int(max_slices))
    if len(unique) > cap:
        return unique[:cap], len(unique)
    return unique, None


def resolve_fanout_slices(
    *,
    wave_slices: list[str] | None,
    decompose_plan: list[dict[str, Any]] | None,
    plan: WavePlan | None,
    max_slices: int,
    require_plan: bool = True,
) -> FanoutResolution:
    """Resolve maker slice ids from LLM artifact only (+ engine clamp)."""
    source: Literal["decompose_plan", "wave_slices", "wave_plan", "missing_plan"]
    raw: list[str]

    if decompose_plan:
        raw = [
            str(spec.get("slice") or spec.get("description") or f"s{i}")
            for i, spec in enumerate(decompose_plan)
        ]
        source = "decompose_plan"
    elif wave_slices:
        raw = list(wave_slices)
        source = "wave_slices"
    elif plan is not None and plan.resolved_slice_ids():
        raw = plan.resolved_slice_ids()
        source = "wave_plan"
    else:
        detail = (
            "LLM wave plan required but missing or empty; "
            "architecture must emit structured WavePlan findings "
            "before makers spawn"
        )
        logger.warning("%s", detail)
        return FanoutResolution(
            slices=[],
            source="missing_plan",
            clamped_from=None,
            plan=None,
            detail=detail,
        )

    clamped, clamped_from = clamp_slice_list(raw, max_slices=max_slices)
    if not clamped:
        detail = "wave plan resolved to an empty slice list after clamp"
        if require_plan:
            return FanoutResolution(
                slices=[],
                source="missing_plan",
                clamped_from=clamped_from,
                plan=plan if source == "wave_plan" else None,
                detail=detail,
            )
        return FanoutResolution(
            slices=[],
            source="missing_plan",
            clamped_from=clamped_from,
            plan=None,
            detail=detail,
        )

    return FanoutResolution(
        slices=clamped,
        source=source,
        clamped_from=clamped_from,
        plan=plan if source == "wave_plan" else None,
        detail="",
    )


def apply_wave_plan_to_state_fields(plan: WavePlan) -> dict[str, Any]:
    """Derive RailJobState field updates from a validated plan (unclamped)."""
    names = plan.resolved_slice_ids()
    updates: dict[str, Any] = {
        "wave_slices": names or None,
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
    wave_slices: list[str] | None = None,
    slices: list[dict[str, Any] | WavePlanSlice] | None = None,
    rationale: str | None = None,
    independence: str | None = None,
    max_waves: int | None = None,
    scout_count: int | None = None,
) -> WavePlan:
    """Build a validated ``WavePlan`` from tool / API arguments."""
    rich: list[WavePlanSlice] = []
    if slices:
        for item in slices:
            if isinstance(item, WavePlanSlice):
                rich.append(item)
            else:
                rich.append(WavePlanSlice.model_validate(item))
    return WavePlan.model_validate(
        {
            "wave_slices": list(wave_slices or []),
            "slices": rich,
            "rationale": rationale,
            "independence": independence,
            "max_waves": max_waves,
            "scout_count": scout_count,
        }
    )


def sort_decompose_plan_by_priority(
    decompose_plan: list[dict[str, Any]] | None,
) -> list[dict[str, Any]] | None:
    """Return a copy of decompose_plan sorted by priority descending."""
    if not decompose_plan:
        return decompose_plan
    return sorted(
        list(decompose_plan),
        key=lambda spec: int(spec.get("priority") or 75),
        reverse=True,
    )
