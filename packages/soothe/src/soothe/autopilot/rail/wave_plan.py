"""Structured wave fan-out plan for LoopRail.

LoopRail owns fan-out *contract* (YAML ``fanout.require_plan`` / counters).
The **LLM** owns fan-out *policy* (flat leaf slice ids). Autopilot applies the
plan into ``RailJobState`` (SoT: ``wave_slices`` / ``decompose_plan`` in
``rail_state.json``).

Transfer forms (any may supply a flat WavePlan):

- Structured completion fields (``wave_plan`` / ``wave_plan_path``)
- Recommended dumps: ``$SOOTHE_DATA_DIR/jobs/{id}/wave-plan.json`` and
  ``<workspace>/.soothe/wave-plan.json``
- Declarative workspace allowlist (``docs/waveplan.json``, …)
- Completion findings / evidence JSON blob

Nested waves/slices are forbidden (RFC-232): reject, do not flatten.
Missing plan fails closed when ``require_plan`` is true.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationError, field_validator

logger = logging.getLogger(__name__)

# Hard cut: removed pre-Slice fan-out wire keys (no dual-read).
_REMOVED_WIRE_KEYS = frozenset({"wave_modules", "modules", "module"})

# Keys that mark a nested ownership tree (forbidden on wire).
_NESTED_CHILD_KEYS = frozenset({"slices", "children", "waves", "wave_slices"})

WAVE_PLAN_FILENAME = "wave-plan.json"

# Declarative convenience paths under the job workspace (not prose scraping).
WAVE_PLAN_WORKSPACE_ALLOWLIST: tuple[str, ...] = (
    "docs/waveplan.json",
    "docs/wave-plan.json",
    "waveplan.json",
    "wave-plan.json",
)


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
    """Machine contract for LLM-determined ready-DAG width (CE findings)."""

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


@dataclass(frozen=True)
class WavePlanIngestResult:
    """Outcome of parsing a WavePlan candidate from any transfer form."""

    plan: WavePlan | None = None
    detail: str = ""
    source_path: str | None = None


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


def _reject_removed_wire_keys(raw: dict[str, Any], *, source: str) -> str | None:
    """Return a reject reason if payload uses removed pre-Slice fan-out keys."""
    found = sorted(k for k in raw if k in _REMOVED_WIRE_KEYS)
    if not found:
        nested = raw.get("slices")
        if isinstance(nested, list):
            for item in nested:
                if isinstance(item, dict) and "module" in item:
                    found = ["slices[].module"]
                    break
    if found:
        msg = f"uses removed keys {found}; use flat wave_slices / slices / slice (source={source})"
        logger.warning("Wave plan (%s) %s", source, msg)
        return msg
    return None


def _entry_has_nested_children(item: dict[str, Any]) -> bool:
    """True when a list entry encodes a nested wave/slice tree."""
    for key in _NESTED_CHILD_KEYS:
        val = item.get(key)
        if isinstance(val, (list, dict)) and val:
            return True
    return False


def _nesting_reject_reason(raw: dict[str, Any], *, source: str) -> str | None:
    """Return a reason if the payload uses nested waves/slices (RFC-232)."""
    if "waves" in raw and isinstance(raw.get("waves"), (list, dict)):
        return (
            f"nested waves forbidden (top-level waves); emit flat wave_slices "
            f"string list or flat slices[] (source={source})"
        )

    ws = raw.get("wave_slices")
    if isinstance(ws, dict):
        return (
            f"nested waves forbidden (wave_slices is an object/dict); emit "
            f'wave_slices as ["a","b"] — do not key by WAVE-* (source={source})'
        )
    if isinstance(ws, list):
        for i, item in enumerate(ws):
            if isinstance(item, dict) and _entry_has_nested_children(item):
                return (
                    f"nested slices forbidden (wave_slices[{i}] contains "
                    f"child slices/waves); flat leaf ids only (source={source})"
                )
            if isinstance(item, dict) and ("wave_id" in item or "wave" in item):
                return (
                    f"nested waves forbidden (wave_slices[{i}] looks like a "
                    f"wave object); flat leaf ids only (source={source})"
                )

    slices = raw.get("slices")
    if isinstance(slices, list):
        for i, item in enumerate(slices):
            if isinstance(item, dict) and _entry_has_nested_children(item):
                return (
                    f"nested slices forbidden (slices[{i}] contains child "
                    f"slices/waves); flat leaf entries only (source={source})"
                )

    for field in ("rationale", "independence"):
        val = raw.get(field)
        if isinstance(val, (dict, list)):
            return (
                f"{field} must be a string (or omitted), not {type(val).__name__} (source={source})"
            )

    return None


def _coerce_flat_aliases(raw: dict[str, Any]) -> dict[str, Any]:
    """Return a shallow-copied dict with flat-only wire aliases normalized.

    Does not flatten nested WAVE trees (those are rejected earlier).
    """
    out = dict(raw)

    for field in ("rationale", "independence"):
        val = out.get(field)
        if val is None or isinstance(val, str) or isinstance(val, (dict, list)):
            continue
        out[field] = str(val)

    slices = out.get("slices")
    if isinstance(slices, list):
        coerced_slices: list[Any] = []
        changed = False
        for item in slices:
            if not isinstance(item, dict):
                coerced_slices.append(item)
                continue
            entry = dict(item)
            if "slice" not in entry:
                for alias in ("name", "id"):
                    alias_val = entry.get(alias)
                    if isinstance(alias_val, str) and alias_val.strip():
                        entry["slice"] = alias_val.strip()
                        changed = True
                        break
            coerced_slices.append(entry)
        if changed:
            out["slices"] = coerced_slices

    ws = out.get("wave_slices")
    if isinstance(ws, list) and ws and all(isinstance(x, dict) for x in ws):
        # Flat list of leaf objects → promote to rich slices when no nesting.
        rich: list[dict[str, Any]] = []
        for item in ws:
            if not isinstance(item, dict):
                return out
            entry = dict(item)
            if "slice" not in entry:
                for alias in ("name", "id", "slice_id"):
                    alias_val = entry.get(alias)
                    if isinstance(alias_val, str) and alias_val.strip():
                        entry["slice"] = alias_val.strip()
                        break
            if isinstance(entry.get("slice"), str) and entry["slice"].strip():
                rich.append(entry)
            else:
                return out  # cannot coerce safely
        if rich and not out.get("slices"):
            out["slices"] = rich
            out["wave_slices"] = [str(e["slice"]).strip() for e in rich]

    return out


def _validation_error_detail(exc: Exception, *, source: str) -> str:
    if isinstance(exc, ValidationError):
        errs = exc.errors()
        if errs:
            first = errs[0]
            loc = ".".join(str(p) for p in first.get("loc") or ())
            msg = first.get("msg") or str(exc)
            if loc:
                return f"{loc}: {msg} (source={source})"
            return f"{msg} (source={source})"
    return f"{exc} (source={source})"


def diagnose_wave_plan_payload(raw: Any, *, source: str = "payload") -> WavePlanIngestResult:
    """Parse and validate a WavePlan candidate; return plan or reject detail.

    Unwraps a nested ``wave_plan`` object when the outer dict has no slices
    (agents often wrap policy under that key). Nested waves/slices are
    rejected without flattening (RFC-232).
    """
    if isinstance(raw, str):
        text = raw.strip()
        if not text:
            return WavePlanIngestResult(detail=f"empty string (source={source})")
        try:
            raw = json.loads(text)
        except json.JSONDecodeError:
            # May still contain embedded objects; caller uses embed scan.
            return WavePlanIngestResult(detail=f"not a JSON object (source={source})")
    if not isinstance(raw, dict):
        return WavePlanIngestResult(
            detail=f"expected JSON object, got {type(raw).__name__} (source={source})"
        )

    removed = _reject_removed_wire_keys(raw, source=source)
    if removed:
        return WavePlanIngestResult(detail=removed)

    nesting = _nesting_reject_reason(raw, source=source)
    if nesting:
        logger.warning("Wave plan nesting rejected (%s): %s", source, nesting)
        return WavePlanIngestResult(detail=nesting)

    coerced = _coerce_flat_aliases(raw)

    try:
        plan = WavePlan.model_validate(coerced)
    except Exception as exc:
        detail = _validation_error_detail(exc, source=source)
        logger.warning("Wave plan schema validation failed (%s): %s", source, detail)
        return WavePlanIngestResult(detail=detail)

    if plan.resolved_slice_ids() or plan.scout_count is not None:
        return WavePlanIngestResult(plan=plan)

    nested = coerced.get("wave_plan")
    if isinstance(nested, dict):
        return diagnose_wave_plan_payload(nested, source=f"{source}.wave_plan")

    detail = f"has no slices or scout_count (source={source})"
    logger.warning("Wave plan (%s) %s", source, detail)
    return WavePlanIngestResult(detail=detail)


def parse_wave_plan_payload(raw: Any, *, source: str = "payload") -> WavePlan | None:
    """Validate a dict (or JSON string) as ``WavePlan`` (slice schema only)."""
    return diagnose_wave_plan_payload(raw, source=source).plan


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


def _prefer_ingest_detail(current: str, candidate: str) -> str:
    """Prefer nesting/schema details over generic missing-JSON messages."""
    if not candidate:
        return current
    if not current:
        return candidate
    cand_l = candidate.lower()
    cur_l = current.lower()
    if "nested" in cand_l and "nested" not in cur_l:
        return candidate
    if "nested" in cur_l:
        return current
    if "not a json" in cur_l or "empty string" in cur_l:
        return candidate
    if ":" in candidate and ":" not in current:
        return candidate
    return candidate


def diagnose_wave_plan_from_findings(
    findings: list[Any] | None,
) -> WavePlanIngestResult:
    """Extract a WavePlan from structured goal findings; retain reject detail."""
    if not findings:
        return WavePlanIngestResult(detail="no WavePlan JSON found in completion findings/evidence")

    best_detail = ""
    for idx, item in enumerate(findings):
        if isinstance(item, dict):
            result = diagnose_wave_plan_payload(item, source=f"findings[{idx}]")
            if result.plan is not None:
                return result
            best_detail = _prefer_ingest_detail(best_detail, result.detail)
            continue
        if not isinstance(item, str):
            continue
        text = item.strip()
        result = diagnose_wave_plan_payload(text, source=f"findings[{idx}]")
        if result.plan is not None:
            return result
        best_detail = _prefer_ingest_detail(best_detail, result.detail)
        for embed_i, obj in enumerate(iter_embedded_json_objects(text)):
            emb = diagnose_wave_plan_payload(obj, source=f"findings[{idx}].embed[{embed_i}]")
            if emb.plan is not None and emb.plan.resolved_slice_ids():
                return emb
            best_detail = _prefer_ingest_detail(best_detail, emb.detail)

    return WavePlanIngestResult(
        detail=best_detail or "no usable flat WavePlan in completion findings/evidence"
    )


def parse_wave_plan_from_findings(findings: list[Any] | None) -> WavePlan | None:
    """Extract a WavePlan from structured goal findings (not prose scrapes)."""
    return diagnose_wave_plan_from_findings(findings).plan


# Cap for WavePlan JSON on goal-completion contribution findings (host re-attach).
WAVE_PLAN_FINDING_CAP = 8000

_SEND_BACK_BASE = (
    "Architecture requires a flat WavePlan (wave_slices string list or flat "
    "slices[{slice,…}]). Host applies it into job rail state. Nested "
    "waves/slices are not allowed. Transfer via any of: completion "
    "wave_plan / wave_plan_path fields; recommended "
    "$SOOTHE_DATA_DIR/jobs/{job_id}/wave-plan.json or "
    "<workspace>/.soothe/wave-plan.json; allowlisted workspace paths "
    "(docs/waveplan.json, …); or a flat JSON blob in the goal completion "
    "report. Custom paths outside the allowlist must set wave_plan_path."
)


def architecture_wave_plan_send_back_reason(detail: str | None = None) -> str:
    """Build architecture-gate send_back text (base contract + optional detail)."""
    cleaned = (detail or "").strip()
    if not cleaned:
        return _SEND_BACK_BASE
    return f"{_SEND_BACK_BASE} Detail: {cleaned[:600]}"


def wave_plan_to_dict(plan: WavePlan) -> dict[str, Any]:
    """Serialize a validated WavePlan to a JSON-ready dict."""
    payload: dict[str, Any] = {}
    if plan.wave_slices:
        payload["wave_slices"] = list(plan.wave_slices)
    if plan.slices:
        payload["slices"] = [s.model_dump(mode="json") for s in plan.slices]
    if plan.independence is not None:
        payload["independence"] = plan.independence
    if plan.rationale is not None:
        payload["rationale"] = plan.rationale
    if plan.scout_count is not None:
        payload["scout_count"] = plan.scout_count
    if plan.max_waves is not None:
        payload["max_waves"] = plan.max_waves
    return payload


def wave_plan_to_findings_json(plan: WavePlan) -> str:
    """Serialize a validated WavePlan to bare JSON for completion findings."""
    return json.dumps(wave_plan_to_dict(plan), ensure_ascii=False, separators=(",", ":"))


def jobs_wave_plan_path(jobs_root: Path, job_id: str) -> Path | None:
    """Recommended host dump: ``{jobs_root}/{job_id}/wave-plan.json``."""
    safe = job_id.replace("/", "_").replace("\\", "_").strip()
    if not safe or ".." in safe:
        return None
    return Path(jobs_root).expanduser().resolve() / safe / WAVE_PLAN_FILENAME


def workspace_wave_plan_path(workspace: Path) -> Path:
    """Recommended workspace dump: ``<workspace>/.soothe/wave-plan.json``."""
    return Path(workspace).expanduser().resolve() / ".soothe" / WAVE_PLAN_FILENAME


def dump_wave_plan(path: Path, plan: WavePlan) -> None:
    """Write flat WavePlan JSON to ``path`` (best-effort caller handles errors)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(wave_plan_to_dict(plan), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def diagnose_wave_plan_from_file(
    path: Path,
    *,
    source: str | None = None,
) -> WavePlanIngestResult:
    """Load and validate a WavePlan JSON file."""
    path = Path(path)
    label = source or str(path)
    if not path.is_file():
        return WavePlanIngestResult(detail=f"file not found (source={label})")
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        return WavePlanIngestResult(detail=f"read failed: {exc} (source={label})")
    result = diagnose_wave_plan_payload(text, source=label)
    if result.plan is not None:
        return WavePlanIngestResult(
            plan=result.plan,
            detail="",
            source_path=str(path.resolve()),
        )
    return result


def _is_under_root(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def resolve_wave_plan_path(
    raw_path: str,
    *,
    workspace: Path | None = None,
    jobs_root: Path | None = None,
    job_id: str | None = None,
) -> Path | None:
    """Resolve a declared path under workspace or jobs root; reject escape."""
    cleaned = (raw_path or "").strip()
    if not cleaned:
        return None
    candidate = Path(cleaned).expanduser()
    roots: list[Path] = []
    if workspace is not None:
        roots.append(Path(workspace).expanduser().resolve())
    if jobs_root is not None and job_id:
        job_dir = jobs_wave_plan_path(Path(jobs_root), job_id)
        if job_dir is not None:
            roots.append(job_dir.parent.resolve())
        roots.append(Path(jobs_root).expanduser().resolve())

    if candidate.is_absolute():
        resolved = candidate.resolve()
        if any(_is_under_root(resolved, root) for root in roots):
            return resolved
        return None

    # Relative: try workspace first, then jobs/{id}/.
    if workspace is not None:
        ws = Path(workspace).expanduser().resolve()
        resolved = (ws / candidate).resolve()
        if _is_under_root(resolved, ws):
            return resolved
    if jobs_root is not None and job_id:
        job_file = jobs_wave_plan_path(Path(jobs_root), job_id)
        if job_file is not None:
            job_dir = job_file.parent.resolve()
            resolved = (job_dir / candidate).resolve()
            if _is_under_root(resolved, job_dir):
                return resolved
    return None


def diagnose_wave_plan_from_sources(
    *,
    wave_plan: dict[str, Any] | WavePlan | None = None,
    wave_plan_path: str | None = None,
    workspace: Path | str | None = None,
    jobs_root: Path | str | None = None,
    job_id: str | None = None,
    findings: list[Any] | None = None,
) -> WavePlanIngestResult:
    """Ingest WavePlan from structured wire, dumps, allowlist, then findings.

    Order: inline ``wave_plan`` → ``wave_plan_path`` → jobs dump → workspace
    ``.soothe/wave-plan.json`` → workspace allowlist → findings/evidence blob.
    """
    best_detail = ""
    ws = Path(workspace).expanduser().resolve() if workspace else None
    jr = Path(jobs_root).expanduser().resolve() if jobs_root else None

    if isinstance(wave_plan, WavePlan):
        if wave_plan.resolved_slice_ids() or wave_plan.scout_count is not None:
            return WavePlanIngestResult(plan=wave_plan)
        best_detail = _prefer_ingest_detail(
            best_detail, "contribution.wave_plan has no slices or scout_count"
        )
    elif isinstance(wave_plan, dict):
        result = diagnose_wave_plan_payload(wave_plan, source="contribution.wave_plan")
        if result.plan is not None:
            return result
        best_detail = _prefer_ingest_detail(best_detail, result.detail)

    if wave_plan_path and str(wave_plan_path).strip():
        resolved = resolve_wave_plan_path(
            str(wave_plan_path),
            workspace=ws,
            jobs_root=jr,
            job_id=job_id,
        )
        if resolved is None:
            best_detail = _prefer_ingest_detail(
                best_detail,
                f"wave_plan_path escapes workspace/jobs root: {wave_plan_path!r}",
            )
        else:
            result = diagnose_wave_plan_from_file(
                resolved, source=f"contribution.wave_plan_path:{resolved}"
            )
            if result.plan is not None:
                return result
            best_detail = _prefer_ingest_detail(best_detail, result.detail)

    if jr is not None and job_id:
        job_path = jobs_wave_plan_path(jr, job_id)
        if job_path is not None and job_path.is_file():
            result = diagnose_wave_plan_from_file(job_path, source=f"jobs_dump:{job_path}")
            if result.plan is not None:
                return result
            best_detail = _prefer_ingest_detail(best_detail, result.detail)

    if ws is not None:
        ws_dump = workspace_wave_plan_path(ws)
        if ws_dump.is_file():
            result = diagnose_wave_plan_from_file(ws_dump, source=f"workspace_dump:{ws_dump}")
            if result.plan is not None:
                return result
            best_detail = _prefer_ingest_detail(best_detail, result.detail)
        for rel in WAVE_PLAN_WORKSPACE_ALLOWLIST:
            candidate = (ws / rel).resolve()
            if not candidate.is_file():
                continue
            if not _is_under_root(candidate, ws):
                continue
            result = diagnose_wave_plan_from_file(candidate, source=f"allowlist:{rel}")
            if result.plan is not None:
                return result
            best_detail = _prefer_ingest_detail(best_detail, result.detail)

    findings_result = diagnose_wave_plan_from_findings(findings)
    if findings_result.plan is not None:
        return findings_result
    best_detail = _prefer_ingest_detail(best_detail, findings_result.detail)

    return WavePlanIngestResult(
        detail=best_detail
        or "no usable flat WavePlan from structured fields, dumps, allowlist, or findings"
    )


def extract_wave_plan_from_plan_result_texts(
    *,
    evidence_summary: str | None = None,
    full_output: str | None = None,
) -> WavePlan | None:
    """Parse WavePlan from untruncated PlanResult text fields (completion wire)."""
    candidates: list[Any] = []
    for text in (evidence_summary, full_output):
        if isinstance(text, str) and text.strip():
            candidates.append(text)
    return parse_wave_plan_from_findings(candidates)


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
    """Resolve maker slice ids from CE/rail state only (+ engine clamp)."""
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
            "architecture must supply a flat WavePlan via structured "
            "fields, recommended dumps, allowlist path, or completion findings "
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
