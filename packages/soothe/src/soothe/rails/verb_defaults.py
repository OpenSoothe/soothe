"""Default catalog-verb goal briefs for Rail Exec (RFC-231 M1/M2).

Rails override via YAML ``verbs.<name>.brief`` or ``do:`` (M3). Templates may
include ``{job_id}``; interpolation is literal replace only.
"""

from __future__ import annotations

from typing import Any

# Host defaults for Python ``_do_*`` fallback when a rail has no ``do:`` recipe.
# Builtin greenfield/migration ship ``do:`` for plan_milestones.

DEFAULT_VERB_BRIEFS: dict[str, str] = {
    "plan_milestones": (
        "Architecture and milestone map for job {job_id}. "
        "Define Slice boundaries (independent parallel ownership units — "
        "features, tasks, packages, or stages), wave-1 independent slices, "
        "wave acceptance criteria, and git commit milestones. "
        "Do not implement product code here.\n\n"
        "REQUIRED deliverable: include one bare WavePlan JSON object in the "
        "goal completion report (final evidence / completion findings on the "
        "wire). The host applies fan-out from that completion finding into "
        "job rail state. Do NOT write FINDINGS.md, wave-plan.json, or any "
        "other project/jobs path as the fan-out deliverable — those files "
        "are ignored. Schema example:\n"
        '{"wave_slices":["core","api","tests"],'
        '"independence":"disjoint write-sets per slice",'
        '"rationale":"why this partition"}\n'
        "Optionally use rich `slices` entries "
        '({"slice","description","priority","tags"}) and/or `max_waves`. '
        "Prose alone is not enough — never substitute a fixed default "
        "slice list. Slices must be independent (no overlapping primary "
        "write sets)."
    ),
    "review": (
        "Diff-scoped code review for job {job_id}. "
        "Review the milestone commit range (not an unclean dirty tree). "
        "Record findings; block on design/security issues; do not "
        "re-implement features."
    ),
}

DEFAULT_VERB_TAGS: dict[str, list[str]] = {
    "plan_milestones": ["architecture", "planning", "milestones"],
}

DEFAULT_VERB_ROLES: dict[str, str] = {
    "plan_milestones": "planner",
}


def interpolate_brief(template: str, *, job_id: str) -> str:
    """Replace ``{job_id}`` only (no full ``str.format``)."""
    return template.replace("{job_id}", job_id)


def resolve_verb_field(
    verb: str,
    field: str,
    *,
    overrides: dict[str, dict[str, Any]] | None,
    defaults: dict[str, Any],
) -> Any | None:
    """Return override[field] if set, else defaults[verb], else None."""
    body = (overrides or {}).get(verb) or {}
    if field in body and body[field] is not None:
        return body[field]
    return defaults.get(verb)


def resolve_verb_brief(
    verb: str,
    *,
    job_id: str,
    overrides: dict[str, dict[str, Any]] | None,
) -> str | None:
    """Resolve and interpolate a verb brief, or None if unknown."""
    raw = resolve_verb_field(verb, "brief", overrides=overrides, defaults=DEFAULT_VERB_BRIEFS)
    if not isinstance(raw, str) or not raw.strip():
        return None
    return interpolate_brief(raw, job_id=job_id)
