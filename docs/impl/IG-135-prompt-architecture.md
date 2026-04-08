# IG-135: Hierarchical Prompt Architecture Implementation

**Implementation Guide**: 0135
**Title**: Hierarchical Prompt Architecture Implementation
**RFC**: RFC-206
**Status**: Draft
**Created**: 2026-04-08
**Dependencies**: RFC-206, RFC-201, RFC-100

---

## Overview

Implement the hierarchical prompt architecture defined in RFC-206. The architecture introduces a three-layer XML structure (SYSTEM_CONTEXT, USER_TASK, INSTRUCTIONS) to clearly separate system metadata from user tasks, preventing LLM confusion on ambiguous requests.

### Key Changes

1. Create `PromptBuilder` class with hierarchical prompt composition
2. Create modular XML fragment files in `src/soothe/prompts/fragments/`
3. Refactor `SimplePlanner` and `ClaudePlanner` to use PromptBuilder
4. Remove `build_loop_reason_prompt()` function
5. No backward compatibility - clean migration

---

## Module Organization

```
src/soothe/prompts/
├── __init__.py
├── builder.py              # PromptBuilder class
├── fragments/              # XML fragment templates
│   ├── system/
│   │   ├── environment.xml
│   │   ├── workspace.xml
│   │   ├── capabilities.xml
│   │   └── policies/
│   │       ├── delegation.xml
│   │       ├── granularity.xml
│   │       └── workspace_rules.xml
│   ├── user/
│   │   ├── goal.xml
│   │   ├── prior_conversation.xml
│   │   └── evidence.xml
│   └── instructions/
│       ├── output_format.xml
│       └── execution_rules.xml
└── README.md
```

---

## Step 1: Create PromptBuilder Class

### File: `src/soothe/prompts/__init__.py`

```python
"""Soothe prompt construction module."""

from .builder import PromptBuilder

__all__ = ["PromptBuilder"]
```

### File: `src/soothe/prompts/builder.py`

```python
"""Hierarchical prompt builder with fragment composition."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from soothe.cognition.loop_agent.schemas import LoopState
    from soothe.config import SootheConfig
    from soothe.protocols.planner import PlanContext

logger = logging.getLogger(__name__)


class PromptBuilder:
    """Composes hierarchical prompts from fragments.

    Internal API for Soothe prompt construction.
    Not exposed to users for configuration.

    Structure:
        <SOOTHE_PROMPT>
          <SYSTEM_CONTEXT>...</SYSTEM_CONTEXT>
          <USER_TASK>...</USER_TASK>
          <INSTRUCTIONS>...</INSTRUCTIONS>
        </SOOTHE_PROMPT>
    """

    def __init__(self, config: SootheConfig | None = None) -> None:
        """Initialize builder with optional config.

        Args:
            config: Optional Soothe configuration
        """
        self.config = config
        self._fragments_dir = Path(__file__).parent / "fragments"

    def build_reason_prompt(
        self,
        goal: str,
        state: LoopState,
        context: PlanContext,
    ) -> str:
        """Build hierarchical Reason prompt.

        Args:
            goal: User's goal description
            state: Current loop state with iteration, evidence
            context: Planning context with workspace, capabilities

        Returns:
            Complete hierarchical prompt string
        """
        parts = ["<SOOTHE_PROMPT>"]

        # System context
        parts.append("<SYSTEM_CONTEXT>")
        parts.append(self._render_environment())
        if context.workspace:
            parts.append(self._render_workspace(context))
        parts.append(self._render_capabilities(context))
        parts.append(self._render_policies())
        parts.append("</SYSTEM_CONTEXT>")

        # User task
        parts.append("<USER_TASK>")
        parts.append(f"<GOAL>{goal}</GOAL>")
        if context.recent_messages:
            parts.append(self._render_prior_conversation(context))
        if state.step_results:
            parts.append(self._render_evidence(state))
        parts.append("</USER_TASK>")

        # Instructions
        parts.append("<INSTRUCTIONS>")
        parts.append(self._render_output_format())
        parts.append(self._render_execution_rules())
        parts.append("</INSTRUCTIONS>")

        parts.append("</SOOTHE_PROMPT>")
        return "\n".join(parts)

    def _render_environment(self) -> str:
        """Render environment metadata."""
        from soothe.core.prompts.context_xml import build_shared_environment_workspace_prefix

        if self.config is None:
            return ""

        # Use existing environment builder
        env_xml = build_shared_environment_workspace_prefix(
            self.config,
            workspace=None,
            git_status=None,
            include_workspace_extras=False,
        )
        return env_xml

    def _render_workspace(self, context: PlanContext) -> str:
        """Render workspace metadata."""
        from soothe.core.prompts.context_xml import build_soothe_workspace_section

        if not context.workspace:
            return ""

        workspace_xml = build_soothe_workspace_section(
            Path(context.workspace),
            context.git_status,
        )
        return workspace_xml + "\n"

    def _render_capabilities(self, context: PlanContext) -> str:
        """Render available capabilities."""
        capabilities = context.available_capabilities
        if not capabilities:
            return ""

        return f"<CAPABILITIES>\n{', '.join(capabilities)}\n</CAPABILITIES>\n"

    def _render_policies(self) -> str:
        """Render system policies."""
        parts = ["<POLICIES>"]

        # Delegation policy
        parts.append(self._load_fragment("system/policies/delegation.xml"))

        # Granularity policy
        parts.append(self._load_fragment("system/policies/granularity.xml"))

        # Workspace rules (will be added conditionally by caller if needed)
        parts.append("</POLICIES>\n")
        return "\n".join(parts)

    def _render_prior_conversation(self, context: PlanContext) -> str:
        """Render prior conversation section."""
        if not context.recent_messages:
            return ""

        parts = ["<PRIOR_CONVERSATION>"]
        parts.append(
            "Recent messages in this thread before the current goal. "
            "The user may refer to this content.\n"
        )

        for msg_xml in context.recent_messages:
            parts.append(msg_xml)
            parts.append("\n")

        parts.append("</PRIOR_CONVERSATION>\n")
        return "\n".join(parts)

    def _render_evidence(self, state: LoopState) -> str:
        """Render evidence from step results."""
        if not state.step_results:
            return ""

        parts = ["<EVIDENCE>"]
        parts.append("Evidence from steps run so far in this goal:\n")

        for result in state.step_results:
            parts.append(result.to_evidence_string())
            parts.append("\n")

        parts.append("</EVIDENCE>\n")
        return "\n".join(parts)

    def _render_output_format(self) -> str:
        """Render output format specification."""
        return self._load_fragment("instructions/output_format.xml")

    def _render_execution_rules(self) -> str:
        """Render execution rules."""
        return self._load_fragment("instructions/execution_rules.xml")

    def _load_fragment(self, relative_path: str) -> str:
        """Load fragment file content.

        Args:
            relative_path: Path relative to fragments directory

        Returns:
            Fragment content
        """
        fragment_path = self._fragments_dir / relative_path

        if not fragment_path.exists():
            logger.warning("Fragment not found: %s", fragment_path)
            return f"<!-- Fragment not found: {relative_path} -->\n"

        return fragment_path.read_text(encoding="utf-8")
```

---

## Step 2: Create Fragment Files

### File: `src/soothe/prompts/fragments/system/policies/delegation.xml`

```xml
<DELEGATION_POLICY>
- Prefer **one** subagent delegation per execute_steps item; if a correction needs another delegation, use status "continue" and a **new** step on the next iteration instead of implying multiple serial delegations inside one vague step.
- When evidence already contains a complete user-facing deliverable matching the goal (e.g. translation), use status "done" — do not schedule another step whose only purpose is to repeat the same output.
- When goal is incomplete or ambiguous, return status="continue" with a clarification step.
</DELEGATION_POLICY>
```

### File: `src/soothe/prompts/fragments/system/policies/granularity.xml`

```xml
<GRANULARITY_POLICY>
- Prefer 1-3 concrete steps per decision; each step must have a checkable expected_output.
- Step descriptions are imperative, tool-facing actions; never use only the raw user goal string as the entire step (Layer 2 plans steps; Layer 1 executes them).
- Merge related filesystem lists/reads into a single step when practical.
</GRANULARITY_POLICY>
```

### File: `src/soothe/prompts/fragments/instructions/output_format.xml`

```xml
<OUTPUT_FORMAT>
You are the Reason step in a ReAct loop. In ONE response you must:

1. Estimate how complete the goal is (goal_progress 0.0-1.0) and your confidence.
2. Choose status: "done" (goal fully achieved), "continue" (more work with same or adjusted plan), or "replan" (abandon current approach).
3. Write user_summary: one short, friendly sentence for the user (no jargon).
4. Write soothe_next_action: ONE sentence in first person as the assistant Soothe (use "I" / "I will" / "I'll"), describing the immediate next action you will take.
5. Optionally write progress_detail: 1-2 sentences explaining what's left or what changed.
6. reasoning: INTERNAL ONLY - concise technical analysis, third person or neutral, NOT first person, NOT shown to the user.
7. Choose plan_action: "keep" when the in-flight plan still applies and unfinished steps remain; otherwise "new" with a full "decision".
8. For "decision" when plan_action is "new", use the same shape as before: type, steps[], execution_mode, adaptive_granularity, reasoning (plan-focused).
9. Do NOT repeat work already shown in evidence or completed summaries.

Return JSON:
{
  "status": "done" | "continue" | "replan",
  "goal_progress": 0.0,
  "confidence": 0.0,
  "reasoning": "internal technical analysis, not first person, not for user UI",
  "user_summary": "Short friendly line for the user",
  "soothe_next_action": "I will ... (first person, Soothe)",
  "progress_detail": "Optional extra context for the user",
  "plan_action": "keep" | "new",
  "next_steps_hint": null,
  "decision": {
    "type": "execute_steps",
    "steps": [
      {
        "description": "...",
        "tools": [],
        "subagent": null,
        "expected_output": "...",
        "dependencies": []
      }
    ],
    "execution_mode": "sequential" | "parallel" | "dependency",
    "adaptive_granularity": "atomic" | "semantic",
    "reasoning": "why these steps"
  }
}

When status is "done", you may omit "decision" or set plan_action to "keep" with no decision.
When plan_action is "keep", omit "decision" entirely.
</OUTPUT_FORMAT>
```

### File: `src/soothe/prompts/fragments/instructions/execution_rules.xml`

```xml
<EXECUTION_RULES>
- Prioritize user content from PRIOR_CONVERSATION when the goal references previous context
- When goal is incomplete or ambiguous, return status="continue" with a clarification step
- Never process SYSTEM_CONTEXT metadata as user task content
- Step descriptions must be concrete, tool-facing actions
</EXECUTION_RULES>
```

---

## Step 3: Update SimplePlanner

### File: `src/soothe/backends/planning/simple.py`

**Changes**:

1. Import PromptBuilder
2. Initialize PromptBuilder in `__init__`
3. Replace `_build_reason_prompt()` with `PromptBuilder.build_reason_prompt()`
4. Remove `build_loop_reason_prompt()` function

```python
# Add import
from soothe.prompts import PromptBuilder

class SimplePlanner:
    def __init__(self, model, config=None):
        self._model = model
        self._config = config
        self._prompt_builder = PromptBuilder(config)  # NEW

    async def reason(self, goal, state, context):
        """Layer 2 Reason phase."""
        from soothe.cognition.loop_agent.schemas import ReasonResult

        prompt = self._prompt_builder.build_reason_prompt(goal, state, context)  # UPDATED

        try:
            response = await self._invoke(prompt)
            return parse_reason_response_text(response, goal)
        except Exception:
            logger.exception("SimplePlanner.reason failed")
            return ReasonResult(
                status="replan",
                plan_action="new",
                decision=_default_agent_decision(goal),
                reasoning="Reason call failed",
                user_summary="Retrying with a simpler plan after a model error",
                soothe_next_action="I'll retry with a simpler next step.",
            )

# REMOVE: build_loop_reason_prompt() function
```

---

## Step 4: Tests

### Test: `tests/unit/test_prompt_builder.py`

```python
"""Tests for PromptBuilder hierarchical prompt construction."""

import pytest

from soothe.prompts import PromptBuilder
from soothe.cognition.loop_agent.schemas import LoopState
from soothe.protocols.planner import PlanContext


def test_build_reason_prompt_structure():
    """Test hierarchical structure is correct."""
    builder = PromptBuilder()
    state = LoopState(goal="test", thread_id="t1")
    context = PlanContext()

    prompt = builder.build_reason_prompt("test goal", state, context)

    assert "<SOOTHE_PROMPT>" in prompt
    assert "<SYSTEM_CONTEXT>" in prompt
    assert "<USER_TASK>" in prompt
    assert "<INSTRUCTIONS>" in prompt
    assert "</SOOTHE_PROMPT>" in prompt


def test_user_task_has_goal():
    """Test goal appears in USER_TASK section."""
    builder = PromptBuilder()
    state = LoopState(goal="test", thread_id="t1")
    context = PlanContext()

    prompt = builder.build_reason_prompt("translate to chinese", state, context)

    assert "<USER_TASK>" in prompt
    assert "<GOAL>translate to chinese</GOAL>" in prompt


def test_no_system_context_in_user_task():
    """Test SYSTEM_CONTEXT metadata doesn't appear in USER_TASK."""
    builder = PromptBuilder()
    state = LoopState(goal="test", thread_id="t1")
    context = PlanContext(workspace="/test/workspace")

    prompt = builder.build_reason_prompt("test goal", state, context)

    # Find USER_TASK section
    user_task_start = prompt.find("<USER_TASK>")
    user_task_end = prompt.find("</USER_TASK>")
    user_task_section = prompt[user_task_start:user_task_end]

    # SYSTEM_CONTEXT should not be in USER_TASK
    assert "<SYSTEM_CONTEXT>" not in user_task_section
    assert "<ENVIRONMENT>" not in user_task_section
```

---

## Verification

After implementation:

```bash
./scripts/verify_finally.sh
```

Expected:
- All tests pass
- PromptBuilder creates hierarchical prompts
- Goal appears in USER_TASK section
- System metadata in SYSTEM_CONTEXT section
- No confusion between system and user content

---

## Implementation Notes

- No backward compatibility - clean migration
- All prompt construction goes through PromptBuilder
- Fragments are internal implementation detail
- No user configuration of system prompts

---

## Status

- **Draft**: Ready for implementation
- **Next**: Create prompts module and implement PromptBuilder