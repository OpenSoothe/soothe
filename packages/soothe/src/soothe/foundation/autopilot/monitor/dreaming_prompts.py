"""LLM prompt templates for dreaming distillation (RFC-625 §6).

Structured prompts for 4 distillation modes:
- Episodic: Transform goals into narrative episode summaries
- Procedure: Extract reusable procedures (Skills)
- Semantic: Update project MEMORY.md
- Profile: Extract user preferences and patterns
"""

from __future__ import annotations

# ── Episodic Distillation ───────────────────────────────────────────────────────

EPISODIC_DISTILLATION_PROMPT = """Transform goal execution history into episodic memory summaries.

## Goals to Distill

{goals_detail}

## Execution Ledger Summary

{ledger_summary}

## Distillation Task

For each completed goal, create an episodic memory summary that captures:

1. **Goal purpose**: What was the goal trying to accomplish?
2. **Outcome**: What actually happened? Success, partial success, or failure?
3. **Key steps**: What were the most important actions taken?
4. **Lessons learned**: What insights should be remembered for future similar goals?

Output JSON structure (strict format):
```json
{
  "episodes": [
    {
      "goal_id": "<goal_id>",
      "description": "<goal description>",
      "outcome_summary": "<what happened, 2-3 sentences>",
      "key_steps": ["step 1 description", "step 2 description"],
      "lessons_learned": "<insight for future>"
    }
  ],
  "reasoning": "Overall distillation analysis..."
}
```

Constraints:
- Max {max_episodes} episodes in response
- Focus on completed goals first, then failed goals with lessons
- outcome_summary should be concise but informative
- key_steps should highlight the most impactful actions (max 5 per goal)
- lessons_learned should be actionable for future similar tasks
"""

# ── Procedure Distillation ──────────────────────────────────────────────────────

PROCEDURE_DISTILLATION_PROMPT = """Extract reusable procedures from successful goal execution patterns.

## Successful Goals

{successful_goals}

## Execution Patterns

{execution_patterns}

## Distillation Task

Identify reusable procedures (potential Skills) from goal execution:

1. **Trigger conditions**: What situations would warrant this procedure?
2. **Steps**: What is the reliable sequence of actions?
3. **Tools used**: Which tools proved essential?
4. **Success indicators**: How do we know it worked?

Output JSON structure (strict format):
```json
{
  "procedures": [
    {
      "name": "<procedure_name>",
      "description": "<what this procedure accomplishes>",
      "trigger_conditions": ["condition 1", "condition 2"],
      "steps": ["step 1", "step 2", "step 3"],
      "tools_used": ["tool_name_1", "tool_name_2"]
    }
  ],
  "reasoning": "Procedure extraction analysis..."
}
```

Constraints:
- Only extract procedures with success rate >= {min_success_rate}
- Procedures should be generalizable, not goal-specific
- Steps should be clear and actionable
- Trigger conditions should help identify when to apply
- Name should be descriptive and skill-like (e.g., "debug_test_failure")
"""

# ── Semantic Distillation ──────────────────────────────────────────────────────

SEMANTIC_DISTILLATION_PROMPT = """Generate project MEMORY.md updates from goal execution findings.

## Project Context

{project_context}

## Goal Findings

{goal_findings}

## Current MEMORY.md Sections

{current_sections}

## Distillation Task

Update project semantic memory (MEMORY.md) based on goal execution:

1. **Additions**: New knowledge sections that should be documented
2. **Modifications**: Updates to existing sections with new insights
3. **Sections to update**: Which existing sections need revision

Output JSON structure (strict format):
```json
{
  "additions": [
    "# New Section Title\n\nContent describing the new knowledge..."
  ],
  "modifications": {
    "Existing Section Name": "Updated content with new insights..."
  },
  "sections_to_update": ["Section 1", "Section 2"],
  "reasoning": "Semantic update analysis..."
}
```

Constraints:
- Additions should be formatted as markdown sections
- Modifications should replace or extend existing content
- Focus on project-specific knowledge, not generic patterns
- Consider what would help future goals succeed faster
- Avoid duplicating existing content
"""

# ── Profile Distillation ────────────────────────────────────────────────────────

PROFILE_DISTILLATION_PROMPT = """Extract user preferences and patterns from goal execution history.

## User Interactions

{user_interactions}

## Goal Patterns

{goal_patterns}

## Communication Style Samples

{communication_samples}

## Distillation Task

Update user profile based on interaction patterns:

1. **Communication style**: How does the user prefer to interact?
2. **Preferences**: What patterns indicate preferences?
3. **Recurring goals**: What types of tasks does the user frequently request?
4. **Expertise level**: What technical depth is appropriate?

Output JSON structure (strict format):
```json
{
  "communication_style": "<style description>",
  "preferences": ["prefers detailed explanations", "likes quick summaries"],
  "recurring_goals": ["debug and fix", "feature implementation"],
  "expertise_level": "<beginner|intermediate|advanced|expert>",
  "reasoning": "Profile extraction analysis..."
}
```

Constraints:
- communication_style should capture interaction preferences
- preferences should be actionable (affect response style)
- recurring_goals help prioritize proactive suggestions
- expertise_level guides explanation depth
- Avoid overfitting to single interactions
"""

# ── Helper formatting functions ───────────────────────────────────────────────────


def format_goals_for_episodic(goals: list) -> str:
    """Format goals for episodic distillation prompt."""
    lines = []
    for g in goals:
        status = getattr(g, "status", "unknown")
        desc = getattr(g, "description", "")[:100]
        findings = getattr(g, "findings", [])
        steps_completed = getattr(g, "steps", None)
        if steps_completed:
            completed_steps = getattr(steps_completed, "completed_steps", 0)
            total_steps = getattr(steps_completed, "total_steps", 0)
        else:
            completed_steps = 0
            total_steps = 0

        findings_str = ", ".join(findings[:3]) if findings else "none"
        lines.append(
            f'  - {getattr(g, "id", "unknown")}: [{status}] "{desc}" '
            f"(steps: {completed_steps}/{total_steps}, findings: {findings_str})"
        )
    return "\n".join(lines)


def format_ledger_summary(ledger: list, max_chars: int = 2000) -> str:
    """Format ledger for distillation prompt."""
    # Summarize ledger entries
    phase_counts = {}
    for entry in ledger:
        if isinstance(entry, tuple) and len(entry) >= 2:
            phase = entry[1] or "unknown"
            phase_counts[phase] = phase_counts.get(phase, 0) + 1

    summary_lines = [
        f"Total entries: {len(ledger)}",
        "Phase distribution:",
    ]
    for phase, count in sorted(phase_counts.items()):
        summary_lines.append(f"  - {phase}: {count}")

    return "\n".join(summary_lines)


def format_successful_goals(goals: list) -> str:
    """Format successful goals for procedure extraction."""
    completed = [g for g in goals if getattr(g, "status", "") == "completed"]
    lines = []
    for g in completed:
        desc = getattr(g, "description", "")[:80]
        steps = getattr(g, "steps", None)
        if steps:
            step_nodes = getattr(steps, "nodes", {})
            step_details = [
                getattr(s, "description", "")[:40]
                for s in step_nodes.values()
                if getattr(s, "status", "") == "completed"
            ]
        else:
            step_details = []

        lines.append(f'  - {getattr(g, "id", "unknown")}: "{desc}"')
        for step in step_details[:5]:
            lines.append(f"    → {step}")
    return "\n".join(lines)
