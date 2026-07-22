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

1. **Stale Goals**: Goals pending for too long (> 1 hour) that may need reset or removal
2. **Merge Opportunities**: Similar pending goals that could be consolidated
3. **Decomposition Opportunities**: Completed complex goals that should spawn follow-up goals
4. **Priority Imbalances**: Goals with mismatched priorities vs importance
5. **Dependency Issues**: Goals with unmet or invalid dependencies

Output JSON structure (strict format):
```json
{{
  "reset_goals": ["goal_id1", "goal_id2"],
  "remove_goals": ["goal_id3"],
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
        {{"description": "Subgoal 1...", "priority": 50}},
        {{"description": "Subgoal 2...", "priority": 40}}
      ]
    }}
  ],
  "priority_adjustments": {{"goal_id7": 70, "goal_id8": 30}},
  "reasoning": "Overall DAG health assessment..."
}}
```

Constraints:
- reset_goals: Goals stuck in pending that should retry
- remove_goals: Goals that are no longer relevant (no dependents)
- merge_goals: Combine similar goals to reduce redundancy
- decompose_goals: Split completed complex goals into follow-ups
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

1. **Decomposition**: Should completed goal spawn follow-up sub-goals?
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
      {{"description": "Subgoal from decomposition...", "priority": 45}}
    ]
  }},
  "reasoning": "Analysis of completion impact on DAG..."
}}
```

Constraints:
- new_goals: Create follow-up goals that inherit from completed goal
- redundant_goals: Goals whose purpose was already fulfilled
- ready_goals: Pending goals with newly satisfied dependencies
- decomposition is optional (null if not needed)
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
