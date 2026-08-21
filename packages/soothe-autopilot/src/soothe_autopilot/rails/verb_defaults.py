"""Default catalog-verb goal briefs for Rail Exec (RFC-231 M1/M2).

Rails override via YAML ``verbs.<name>.brief`` or ``do:`` (M3). Templates may
include ``{job_id}``; interpolation is literal replace only.

Discipline fragments (TDD, systematic debugging, parallel dispatch,
``using-git-worktrees``) are appended by helpers so Python builtins and YAML
``do:`` recipes share one SoT (IG-737).
"""

from __future__ import annotations

from typing import Any

# Host defaults for Python ``_do_*`` fallback when a rail has no ``do:`` recipe.
# Builtin greenfield/migration ship ``do:`` for plan_milestones.

# Single SoT for plan_milestones efficiency / parallel-dispatch copy (appended by
# ``apply_planner_waveplan_hints`` — do not duplicate those blocks in rail YAML).
WAVEPLAN_EFFICIENCY_HINT = (
    "\n\nEfficiency: If a recommended dump already exists and is flat, verify "
    "it in one step (wave_slices + string independence + rationale), set "
    "completion wave_plan_path to that file (or inline wave_plan), and "
    "complete. Do not rediscover the whole tree, rewrite the plan repeatedly, "
    "or write markdown validation/completion reports — those are not "
    "deliverables. independence must be a plain string, never a nested object."
)

# Parallel partition policy (dispatching-parallel-agents discipline).
PARALLEL_DISPATCH_HINT = (
    "\n\nParallel dispatch: Partition only into independent domains — "
    "no overlapping primary write-sets, no shared mutable state that would "
    "make concurrent makers interfere. If domains are related (one root cause "
    "could explain all), keep a single slice. Each slice description must be "
    "self-contained (ownership, files/areas, done check)."
)

# Nano builtin skill — makers must invoke explicitly (host may already isolate).
WORKTREE_SKILL_BRIEF = (
    '\n\nREQUIRED: invoke_skill("using-git-worktrees") before any file edits. '
    "If cwd is already under .soothe/worktrees/ (or a linked worktree): reuse it; "
    "do not create another worktree; do not nest. "
    "If on the primary checkout: follow that skill to create "
    ".soothe/worktrees/<slug> (ensure .soothe/ is gitignored). "
    "Never use .worktrees/ or worktrees/ unless the user asked for that layout. "
    "Host-assigned Autopilot worktrees count as already-approved isolation — "
    "skip interactive confirmation and continue in place."
)

TDD_IRON_LAW_BRIEF = (
    "\n\nTDD (mandatory for behavior changes): "
    "NO PRODUCTION CODE WITHOUT A FAILING TEST FIRST. "
    "RED: write one failing behavioral test → run it → confirm it fails for the "
    "right reason. GREEN: minimal code to pass → run again. "
    "REFACTOR: only after green; keep tests green. "
    "If you already wrote code first: delete it and restart from RED "
    "(exceptions: throwaway spike or pure config — state that in the report). "
    "Bug fixes: failing regression test first, then fix."
)

SYSTEMATIC_DEBUG_MAKER_BRIEF = (
    "\n\nSystematic debugging: Fix only after root-cause evidence "
    "(scout findings, failing test, or traced bad value). "
    "One hypothesis at a time. If 3+ fix attempts fail without confirmed "
    "root cause, stop and complete with failure requesting architecture "
    "rethink / branch retry — do not thrash."
)

QA_VERIFY_DISCIPLINE_BRIEF = (
    "\n\nVerification discipline: Run the relevant automated checks "
    "(and the original failing path when fixing a defect). "
    "Report pass/fail with fresh command output — never claim success "
    "from intuition or prior runs. Prefer proving the RED test fails "
    "without the fix when practical."
)


def ensure_waveplan_efficiency_hint(brief: str) -> str:
    """Append ``WAVEPLAN_EFFICIENCY_HINT`` once (idempotent)."""
    text = (brief or "").rstrip()
    if not text:
        return text
    if "Efficiency:" in text and "plain string" in text.lower():
        return text
    return text + WAVEPLAN_EFFICIENCY_HINT


def ensure_parallel_dispatch_hint(brief: str) -> str:
    """Append ``PARALLEL_DISPATCH_HINT`` once (idempotent)."""
    text = (brief or "").rstrip()
    if not text:
        return text
    if "Parallel dispatch:" in text:
        return text
    return text + PARALLEL_DISPATCH_HINT


def ensure_worktree_skill_brief(brief: str) -> str:
    """Append ``WORKTREE_SKILL_BRIEF`` once (idempotent)."""
    text = (brief or "").rstrip()
    if not text:
        return text
    if 'invoke_skill("using-git-worktrees")' in text:
        return text
    return text + WORKTREE_SKILL_BRIEF


def ensure_tdd_iron_law(brief: str) -> str:
    """Append ``TDD_IRON_LAW_BRIEF`` once (idempotent)."""
    text = (brief or "").rstrip()
    if not text:
        return text
    if "NO PRODUCTION CODE WITHOUT A FAILING TEST FIRST" in text:
        return text
    return text + TDD_IRON_LAW_BRIEF


def ensure_systematic_debug_maker(brief: str) -> str:
    """Append ``SYSTEMATIC_DEBUG_MAKER_BRIEF`` once (idempotent)."""
    text = (brief or "").rstrip()
    if not text:
        return text
    if "Systematic debugging:" in text and "3+ fix" in text:
        return text
    return text + SYSTEMATIC_DEBUG_MAKER_BRIEF


def ensure_qa_verify_discipline(brief: str) -> str:
    """Append ``QA_VERIFY_DISCIPLINE_BRIEF`` once (idempotent)."""
    text = (brief or "").rstrip()
    if not text:
        return text
    if "Verification discipline:" in text:
        return text
    return text + QA_VERIFY_DISCIPLINE_BRIEF


def apply_maker_discipline(brief: str) -> str:
    """Worktree skill + TDD + systematic-debug maker rules (idempotent)."""
    text = ensure_worktree_skill_brief(brief)
    text = ensure_tdd_iron_law(text)
    return ensure_systematic_debug_maker(text)


def apply_planner_waveplan_hints(brief: str) -> str:
    """Efficiency + parallel-dispatch hints for architecture planners."""
    text = ensure_waveplan_efficiency_hint(brief)
    return ensure_parallel_dispatch_hint(text)


def scout_explore_brief(*, job_id: str, domain_index: int, domain_hint: str | None = None) -> str:
    """Default scout brief for ``decompose_parallel`` (systematic debugging)."""
    domain = (domain_hint or "").strip() or f"independent domain {domain_index}"
    return (
        f"Systematic debugging / exploration scout for job {job_id}. "
        f"Scope: ONE independent domain — {domain}. "
        "Do not edit production code; do not implement fixes.\n\n"
        "Follow four phases before proposing any fix:\n"
        "1) Root cause — reproduce, read errors in full, gather evidence at "
        "component boundaries\n"
        "2) Pattern — compare working vs broken references\n"
        "3) Single hypothesis — state it; test minimally if needed\n"
        "4) Report only — evidence + hypothesis for the planner/maker\n\n"
        "Iron law: no fixes without root-cause investigation first.\n"
        "Return: domain name, repro steps, failing command output (if any), "
        "root-cause statement, related files. "
        "If multiple unrelated domains exist, cover only this domain — "
        "parallel scouts handle the others."
    )


def plan_implementation_brief(*, job_id: str) -> str:
    """Planner goal brief for ``plan_and_implement``."""
    base = (
        f"Plan implementation for job {job_id}. "
        "Use scout findings (informs). Produce a concrete plan with "
        "file paths, interfaces, and per-task acceptance "
        "(prefer the first failing test or verify command per task). "
        "Partition work into independent domains only when write-sets "
        "do not overlap. Do not implement product code here."
    )
    return ensure_parallel_dispatch_hint(base)


def implement_goal_brief(*, job_id: str) -> str:
    """Maker goal brief for ``plan_and_implement``."""
    base = (
        f"Implement for job {job_id} according to the plan goal. "
        "Stay within planned ownership; commit on an isolated branch when "
        "using a worktree."
    )
    return apply_maker_discipline(base)


def slice_maker_brief(
    *,
    job_id: str,
    slug: str,
    ownership: str,
    branch: str,
    job_branch: str,
    retry: bool = False,
) -> str:
    """Maker brief for ``spawn_wave_makers`` / ``retry_maker`` (+ discipline)."""
    own = (ownership or "").strip() or f"Implement only the '{slug}' slice ownership."
    label = f"Slice maker [{slug}] retry" if retry else f"Slice maker [{slug}]"
    base = (
        f"{label} for job {job_id}. {own} "
        f"Commit on this branch ({branch}); "
        f"the host merges into {job_branch} when you complete. "
        "Do not modify unrelated slices."
    )
    return apply_maker_discipline(base)


def waveplan_verify_existing_brief(*, job_id: str, source: str) -> str:
    """Brief for a minimal StrangeLoop verify of a candidate WavePlan dump.

    Host never auto-accepts a dump; the agent must accept or rewrite.
    """
    return (
        f"Verify candidate WavePlan for job {job_id} before fan-out. "
        f"Candidate source: {source}. "
        "Compare the dump against this job's current goal description and "
        "workspace state. If it is still a correct flat partition "
        "(wave_slices string list or flat slices entries; string independence; "
        "rationale; no nested WAVE trees), complete with wave_plan_path "
        "pointing at that file (or inline wave_plan JSON). "
        "If the dump is stale, wrong for this job, or incomplete, rewrite a "
        "flat WavePlan and complete with that instead. "
        "Do not implement product or migration code. "
        "Do not write markdown validation/completion reports — those are not "
        "deliverables. independence must be a plain string, never a nested object."
    )


DEFAULT_VERB_BRIEFS: dict[str, str] = {
    "plan_milestones": (
        "Architecture and milestone map for job {job_id}. "
        "Define Slice boundaries (independent parallel ownership units — "
        "features, tasks, packages, or stages), wave-1 independent slices, "
        "wave acceptance criteria, and git commit milestones. "
        "Do not implement product code here.\n\n"
        "REQUIRED deliverable: one flat WavePlan JSON object "
        '(wave_slices string list or flat slices[{"slice",…}]; nested '
        "WAVE trees forbidden). Host SoT is job rail state after ingest.\n"
        "Suggested dumps (optional, not required): "
        "<workspace>/.soothe/wave-plan.json or "
        "$SOOTHE_DATA_DIR/jobs/{job_id}/wave-plan.json. Also OK: set "
        "completion wave_plan_path to any file under the workspace, inline "
        "completion wave_plan, or a flat JSON blob in the goal completion "
        "report. Schema example:\n"
        '{"wave_slices":["core","api","tests"],'
        '"independence":"disjoint write-sets per slice",'
        '"rationale":"why this partition"}\n'
        "Optionally use rich flat `slices` entries "
        '({"slice","description","tags"}) and/or `max_waves`. '
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
    # Autoresearch rail defaults (defensive; YAML ``brief:`` overrides win).
    # ``plan_and_implement`` is native-dispatched via autoresearch_exec when
    # rail_id == "autoresearch", so this default only applies if a custom
    # rail without a ``do:`` recipe or ``brief:`` override calls it.
    "plan_and_implement": (
        "Plan and implement for job {job_id}. Produce a concrete plan with "
        "file paths, interfaces, and per-task acceptance, then implement "
        "according to that plan. Stay within planned ownership."
    ),
}

DEFAULT_VERB_TAGS: dict[str, list[str]] = {
    "plan_milestones": ["architecture", "planning", "milestones"],
    # Autoresearch defaults (defensive; YAML overrides win).
    "plan_and_implement": ["planning", "implementation"],
    "review": ["review"],
    "qa_verify": ["qa"],
}

DEFAULT_VERB_ROLES: dict[str, str] = {
    "plan_milestones": "planner",
    # Autoresearch defaults (defensive; YAML overrides win).
    "plan_and_implement": "planner",
    "review": "checker",
    "qa_verify": "qa",
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
    out = interpolate_brief(raw, job_id=job_id)
    if verb == "plan_milestones":
        out = apply_planner_waveplan_hints(out)
    return out
