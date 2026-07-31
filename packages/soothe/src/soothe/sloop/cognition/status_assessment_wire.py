"""Wire coercion for StatusAssessment structured LLM output (IG-668).

Thinking models emit the assessment under a section wrapper
(``{"PLAN_ASSESS": {...}}``), or as tag-wrapped YAML instead of JSON, or with
title-cased enum values. Every one of those carries a usable assessment, so
salvage before validation rather than dropping to the raw-text fallback.
"""

from __future__ import annotations

from typing import Any

import yaml

from soothe.sloop.cognition.wire_envelope import unwrap_schema_envelope
from soothe.sloop.utils.json_parsing import _load_llm_json_dict

# Required property that marks an unwrapped StatusAssessment payload.
_MARKER_KEY = "status"

_STATUS_VALUES: tuple[str, ...] = ("continue", "replan", "done")
_PROGRESS_VALUES: tuple[str, ...] = ("none", "low", "medium", "high", "complete")
_READINESS_VALUES: tuple[str, ...] = ("not_ready", "ready_with_gaps", "ready")


def _normalized_enum(value: Any, allowed: tuple[str, ...]) -> str | None:
    """Return ``value`` matched case-insensitively against ``allowed``, else None."""
    if not isinstance(value, str):
        return None
    candidate = value.strip().lower()
    return candidate if candidate in allowed else None


def coerce_status_assessment_wire_dict(data: dict[str, Any]) -> dict[str, Any]:
    """Salvage common StatusAssessment wire malformations before validation.

    Args:
        data: Parsed structured-output dict (may already be valid).

    Returns:
        Dict safe for ``StatusAssessment`` jsonschema / Pydantic construction.
        Fields the model got wrong are dropped so schema defaults apply.
    """
    if not isinstance(data, dict):
        return data

    out = dict(unwrap_schema_envelope(data, marker_key=_MARKER_KEY))

    for field, allowed in (
        ("status", _STATUS_VALUES),
        ("goal_progress", _PROGRESS_VALUES),
        ("terminal_readiness", _READINESS_VALUES),
    ):
        if field not in out:
            continue
        normalized = _normalized_enum(out[field], allowed)
        if normalized is None:
            out.pop(field)
        else:
            out[field] = normalized

    if "assessment_reasoning" in out and not isinstance(out["assessment_reasoning"], str):
        out["assessment_reasoning"] = str(out["assessment_reasoning"])

    return out


def parse_status_assessment_payload(text: str) -> dict[str, Any]:
    """Parse an assessment mapping from raw model text.

    Accepts JSON (optionally fenced), and YAML mappings that models wrap in
    section tags such as ``<PLAN_ASSESS> ... </PLAN_ASSESS>``.

    Args:
        text: Raw content extracted from the model response.

    Returns:
        Parsed mapping, before wire coercion.

    Raises:
        ValueError: When no mapping can be recovered from ``text``.
    """
    try:
        return _load_llm_json_dict(text)
    except Exception:  # noqa: BLE001 - any parse failure falls through to YAML
        pass

    body = "\n".join(
        line for line in text.splitlines() if not _is_standalone_tag_line(line)
    ).strip()
    if not body:
        msg = "assessment payload is empty after tag stripping"
        raise ValueError(msg)

    try:
        loaded = yaml.safe_load(body)
    except yaml.YAMLError as exc:
        msg = f"assessment payload is neither JSON nor YAML: {exc}"
        raise ValueError(msg) from exc

    if not isinstance(loaded, dict):
        msg = f"assessment payload parsed to {type(loaded).__name__}, expected a mapping"
        raise ValueError(msg)
    return loaded


def _is_standalone_tag_line(line: str) -> bool:
    """Return True for a line holding only an XML-style open or close tag."""
    stripped = line.strip()
    if not (stripped.startswith("<") and stripped.endswith(">")):
        return False
    inner = stripped[1:-1].removeprefix("/").strip()
    return bool(inner) and all(char.isalnum() or char in "_-." for char in inner)


__all__ = [
    "coerce_status_assessment_wire_dict",
    "parse_status_assessment_payload",
]
