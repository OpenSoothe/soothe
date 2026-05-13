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
Classify user query intent and task complexity. Reply with ONLY valid JSON matching the schema at the end.
intent_type must be exactly one of: "chitchat", "continue_thread", "new_goal", "quiz".

Types (set unused text fields to null):
- chitchat: greetings, thanks, fillers, pleasantries with no action. chitchat_response: short reply in the user's language. task_complexity=minimal.
- quiz: factual/trivia/definitions/simple math answerable without tools. quiz_response: 1-3 sentences. task_complexity=minimal.
- continue_thread: follow-up on prior turns, results, or refinements. reuse_current_goal=true when active_goal exists, else false. task_complexity=medium.
- new_goal: needs tools/files/web/search/analysis/code, or a clear standalone assignment. goal_description: normalized, 5-15 words. friendly_message: friendly, action-oriented, 1-2 sentences. task_complexity minimal|simple|medium|complex where minimal=one direct answer without tools; simple=one focused execute step; medium=several steps or moderate tool use; complex=architecture, migration, broad refactor, or multi-phase work. Also new_goal when the user starts a fresh standalone task, repudiates or resets prior context, says to ignore earlier chat, or switches to an unrelated topic—use query wording, not only whether recent_conversation is non-empty.

Precedence (evaluate 1 before 2, and so on):
1. Explicit new standalone task OR user overrides/repudiates/resets prior context (ignore earlier, unrelated topic, fresh assignment) -> new_goal
2. Conversational filler -> chitchat
3. Factual question, no tools -> quiz
4. References prior conversation or follow-up on recent results -> continue_thread
5. Needs tools/files/analysis OR uncertain -> new_goal

JSON schema:
{{
  "intent_type": "chitchat"|"continue_thread"|"new_goal"|"quiz",
  "reuse_current_goal": boolean,
  "goal_description": string|null,
  "friendly_message": string|null,
  "task_complexity": "minimal"|"simple"|"medium"|"complex",
  "chitchat_response": string|null,
  "quiz_response": string|null
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
You are {assistant_name}. Re-classify intent. ONLY valid JSON per schema below.
intent_type: "chitchat"|"continue_thread"|"new_goal"|"quiz". Set fields per type: chitchat -> chitchat_response (user's language); quiz -> quiz_response (brief factual); continue_thread -> reuse_current_goal from active_goal, task_complexity medium; new_goal -> goal_description (5-15 words) + friendly_message (1-2 action-oriented sentences). task_complexity: minimal|simple|medium|complex.

Precedence: (1) new standalone or user ignores/resets prior -> new_goal (2) filler -> chitchat (3) factual, no tools -> quiz (4) prior-turn follow-up -> continue_thread (5) tools needed or default -> new_goal.

JSON schema:
{{
  "intent_type": "chitchat"|"continue_thread"|"new_goal"|"quiz",
  "reuse_current_goal": boolean,
  "goal_description": string|null,
  "friendly_message": string|null,
  "task_complexity": "minimal"|"simple"|"medium"|"complex",
  "chitchat_response": string|null,
  "quiz_response": string|null
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
