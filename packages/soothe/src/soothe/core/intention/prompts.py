"""LLM prompts for intent classification (IG-226, IG-250, IG-325, IG-363, IG-364).

Structured prompts for LLM-driven intent classification with conversation context.
Pure LLM-driven - no keyword heuristics or language detection shortcuts.

Prompt layout (IG-364): static instructions and schema first; variable runtime fields
last inside flat XML structure (no nested wrappers), aligned with AgentLoop plan-style.

XML structure:
- <intent_instructions>: Static content (classification rules, precedence, JSON schema)
- <intent_inputs>: Dynamic runtime fields as flat XML elements
  - <current_time>, <thread_id>, <active_goal>: Runtime context (flat, not nested)
  - <recent_conversation>: Conversation excerpts in <user>/<assistant> blocks
  - <current_query>: User's query text
"""

from __future__ import annotations

# Intent classification prompt (primary classification)
INTENT_CLASSIFICATION_PROMPT = """\
<intent_instructions>
Classify the user's query intent and task complexity.

CRITICAL OUTPUT RULES:
- Return ONLY valid JSON matching the schema below
- "intent_type" MUST be exactly one of: "chitchat", "continue_thread", "new_goal", "quiz"
- Keep "reasoning" short (one sentence)

Intent classification criteria:
- chitchat: Greetings, thanks, fillers, conversational pleasantries needing no action
  → chitchat_response required in detected user language
  → task_complexity=minimal

- quiz: Factual knowledge questions, trivia, definitions, simple math
  → quiz_response required (brief factual answer, 1-3 sentences)
  → task_complexity=minimal

- continue_thread: References prior conversation/results, follow-up actions, refinements
  → reuse_current_goal=true if active_goal exists, false otherwise
  → task_complexity=medium (follow-up actions)

- new_goal: Standalone tasks requiring tools (file ops, web search, analysis, coding)
  → goal_description required (normalized task description, 5-15 words)
  → friendly_message required (friendly, action-oriented, 1-2 sentences)
  → task_complexity: minimal | simple | medium | complex
     - minimal: one direct answer, no tools needed
     - simple: one focused execute step should finish (e.g., count all README files)
     - medium: several steps, moderate exploration or tool use
     - complex: architecture, migration, broad refactor, or deep multi-phase work
  → ALSO use new_goal when the user clearly starts a NEW standalone task, repudiates or
    resets prior context, asks to ignore earlier discussion, or switches topic to
    unrelated work—even if recent_conversation is non-empty. Judge intent from the
    query wording, not from the presence of prior turns alone.

Intent precedence (apply in order):
1. If the user explicitly starts a new standalone task OR repudiates / overrides prior
   context (ignore earlier, new topic unrelated to last turns, fresh assignment) → new_goal
2. If query is conversational filler (greeting/thanks) → chitchat
3. If query is factual knowledge question (no tools needed) → quiz
4. If query references prior conversation or is a follow-up on recent results → continue_thread
5. If query requires tools/files/analysis → new_goal (DEFAULT when uncertain)

Required JSON shape:
{{
  "intent_type": "chitchat"|"continue_thread"|"new_goal"|"quiz",
  "reuse_current_goal": boolean,
  "goal_description": string|null,
  "friendly_message": string|null,
  "task_complexity": "minimal"|"simple"|"medium"|"complex",
  "chitchat_response": string|null,
  "quiz_response": string|null,
  "reasoning": string
}}
</intent_instructions>

<current_time>{current_time}</current_time>

<thread_id>{thread_id}</thread_id>

<active_goal>{active_goal_context}</active_goal>

<recent_conversation>
{conversation_context}
</recent_conversation>

<current_query>
{query}
</current_query>
"""

# Retry prompt (simplified, no conversation context)
INTENT_CLASSIFICATION_RETRY_PROMPT = """\
<intent_classification>
<intent_instructions>
You are {assistant_name}. Re-classify this query's intent.

CRITICAL OUTPUT RULES:
- Return ONLY valid JSON matching the schema
- "intent_type" MUST be exactly one of: "chitchat", "continue_thread", "new_goal", "quiz"
- For "chitchat": set chitchat_response (detect user language from query)
- For "quiz": set quiz_response (brief factual answer)
- For "continue_thread": set reuse_current_goal based on active_goal
- For "new_goal": set goal_description AND friendly_message (action-oriented reinterpretation)
- "task_complexity": minimal | simple | medium | complex
- "reasoning" is REQUIRED

Intent precedence:
1. Explicit new standalone task or user overrides / ignores prior context → new_goal
2. Conversational filler → chitchat
3. Factual knowledge question (no tools) → quiz
4. Prior-turn follow-up or refinement → continue_thread
5. Tool-requiring task → new_goal (DEFAULT)

Required JSON shape:
{{
  "intent_type": "chitchat"|"continue_thread"|"new_goal"|"quiz",
  "reuse_current_goal": boolean,
  "goal_description": string|null,
  "friendly_message": string|null,
  "task_complexity": "minimal"|"simple"|"medium"|"complex",
  "chitchat_response": string|null,
  "quiz_response": string|null,
  "reasoning": string
}}
</intent_instructions>

<intent_inputs>
<current_time>{current_time}</current_time>
<active_goal>{active_goal_context}</active_goal>
<current_query>
{query}
</current_query>
</intent_inputs>
</intent_classification>
"""
