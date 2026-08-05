"""LLM prompt templates for DAG verification (RFC-625 §4).

Structured prompts for:
- DAG health verification (background cycle)
- Post-completion analysis (event-triggered)
- Goal placement analysis (intake)
"""

from __future__ import annotations

# ── DAG Health Verification ───────────────────────────────────────────────────────

DAG_HEALTH_VERIFICATION_PROMPT = """Analyze the goal DAG for health issues and restructuring opportunities.

## DAG Snapshot

Total Goals: {total_goals}
Active Goals: {active_count}
Pending Goals: {pending_count}
Completed Goals: {completed_count}
Failed Goals: {failed_count}

Goal Details:
{goals_detail}

Step Progress Summary:
{step_progress}

## Analysis Required

Identify issues in the goal DAG:

1. **Stale Goals**: Goals pending for too long (> 1 hour) that may need reset
2. **Clutter Removal**: Only cancelled/failed goals with ZERO dependents and ZERO
   non-terminal descendants — never remove job roots or active/suspended goals
3. **Merge Opportunities**: Similar pending goals that could be consolidated (suggestions only)
4. **Decomposition Opportunities**: Completed complex goals that should spawn follow-ups
5. **Priority Imbalances**: Goals with mismatched priorities vs importance
6. **Dependency Issues**: Pipeline goals missing hard depends_on edges — use wire_dependencies

Output JSON structure (strict format):
```json
{{
  "reset_goals": ["goal_id1", "goal_id2"],
  "remove_goals": ["cancelled_clutter_id"],
  "merge_goals": [
    {{
      "goal_ids": ["goal_id4", "goal_id5"],
      "merged_description": "Consolidated description..."
    }}
  ],
  "decompose_goals": [
    {{
      "goal_id": "goal_id6",
      "subgoals": [
        {{"description": "Subgoal 1...", "priority": 50, "depends_on": []}},
        {{"description": "Subgoal 2...", "priority": 40, "depends_on": ["0"]}}
      ]
    }}
  ],
  "wire_dependencies": [
    {{"goal_id": "goal_id_test", "depends_on": ["goal_id_implement"]}}
  ],
  "priority_adjustments": {{"goal_id7": 70, "goal_id8": 30}},
  "reasoning": "Overall DAG health assessment..."
}}
```

Constraints:
- reset_goals: Goals stuck in pending/suspended that should retry —
  NEVER reset goals suspended after consensus send_back budget exhaustion
  (send_back_count >= max_send_backs); those need operator resume, not auto-reset.
  Do reset ordinary suspended/blocked goals whose dependencies are satisfied
  and that are not send_back-exhausted.
- remove_goals: ONLY cancelled or failed clutter with no dependents; NEVER job roots
  (parent_id null) that are still active/pending/suspended; NEVER goals with live children
- merge_goals: Combine similar goals (logged; not always auto-applied)
- decompose_goals: Split completed complex goals into follow-ups; each subgoal MUST
  include depends_on when a pipeline is implied (use sibling index "0","1",… or real IDs)
- wire_dependencies: Set hard depends_on on existing goals to enforce pipeline order.
  NEVER wire a child goal to depend_on a job root (parent_id null). Roots may
  depend on children; children must never depend on the job root.
- All goal IDs MUST exist in current DAG
"""

# ── Post-Completion Verification ──────────────────────────────────────────────────

POST_COMPLETION_VERIFICATION_PROMPT = """Analyze goal completion and identify follow-up opportunities.

## Completed Goal

Goal ID: {completed_goal_id}
Description: {completed_description}
Outcome Summary: {outcome_summary}
Steps Executed: {steps_executed}
Key Findings: {key_findings}
Total Duration: {total_duration_ms}ms
Tokens Used: {total_tokens_used}

## Current DAG State

Pending Goals:
{pending_goals}

Active Goals:
{active_goals}

## Analysis Required

After goal completion, analyze:

1. **Decomposition**: Should completed goal spawn follow-up sub-goals? Prefer null
   when the outcome already delivered the job (e.g. SUMMARY.md / tests present).
2. **Redundancy**: Are pending goals now redundant given completion results?
3. **New Goals**: Should new follow-up goals be created?
4. **Ready Goals**: Which pending goals can now proceed (dependencies satisfied)?

Output JSON structure (strict format):
```json
{{
  "new_goals": [
    {{"description": "Follow-up goal...", "priority": 50, "depends_on": ["{completed_goal_id}"]}}
  ],
  "redundant_goals": ["goal_id_that_is_now_redundant"],
  "ready_goals": ["goal_id_with_deps_now_satisfied"],
  "decomposition": {{
    "goal_id": "{completed_goal_id}",
    "subgoals": [
      {{"description": "Subgoal from decomposition...", "priority": 45, "depends_on": []}}
    ]
  }},
  "reasoning": "Analysis of completion impact on DAG..."
}}
```

Constraints:
- new_goals: Create follow-up goals that inherit from completed goal
- redundant_goals: Goals whose purpose was already fulfilled (cancelled/failed clutter only preferred)
- ready_goals: Pending goals with newly satisfied dependencies
- decomposition is optional (null if not needed); when present, subgoals MUST include
  depends_on for pipeline order (sibling index refs allowed)
- Prefer decomposition=null when key_findings/outcome already show deliverables complete
"""

# ── Goal Placement Analysis ───────────────────────────────────────────────────────

GOAL_PLACEMENT_PROMPT = """Analyze new goal placement in the existing DAG.

## New Goal

Description: {goal_description}

## Current DAG State

Active Goals: {active_count}
Pending Goals: {pending_count}
Recently Completed: {recently_completed}

Existing Goals Detail:
{existing_goals}

## Analysis Required

Determine optimal placement for new goal:

1. **Priority**: What priority should this goal have given current DAG load and importance?
2. **Dependencies**: Should this goal depend on any existing goals?
3. **Informs**: Which goals should be informed by this goal's results?
4. **Merge**: Is this goal similar to an existing pending goal that could be merged?
5. **Complexity**: Estimate execution complexity

Output JSON structure (strict format):
```json
{{
  "priority": 50,
  "depends_on": ["existing_goal_id1"],
  "informs": ["existing_goal_id2"],
  "merge_with": null,
  "complexity": "moderate",
  "reasoning": "Placement decision reasoning..."
}}
```

Constraints:
- priority: 0-100, higher = more urgent (default 50)
- depends_on: Hard dependencies (goal won't run until these complete)
- informs: Soft dependencies (context flows but goal can still run)
- merge_with: Goal ID if similar to existing (null if unique)
- complexity: "simple" (~1-3 steps), "moderate" (~4-8 steps), "complex" (>8 steps)
- All referenced goal IDs MUST exist in current DAG
"""

# ── Helper formatting functions ───────────────────────────────────────────────────


def format_goals_detail(goals: list[dict]) -> str:
    """Format goals list for prompt inclusion."""
    lines = []
    for g in goals:
        deps = ", ".join(g.get("depends_on", [])) or "none"
        status = g.get("status", "unknown")
        priority = g.get("priority", 50)
        desc = g.get("description", "")[:80]
        lines.append(f'  - {g["id"]}: [{status}] pri={priority} deps=[{deps}] "{desc}"')
    return "\n".join(lines)


def format_step_progress(goals: list[dict]) -> str:
    """Format step progress for prompt inclusion."""
    total_steps = sum(g.get("step_count", 0) for g in goals)
    completed_steps = sum(g.get("completed_steps", 0) for g in goals)
    failed_steps = sum(g.get("failed_steps", 0) for g in goals)
    return f"Total: {total_steps} | Completed: {completed_steps} | Failed: {failed_steps}"
