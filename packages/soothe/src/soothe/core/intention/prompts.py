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

# Intent classification prompt (primary classification; routing only — no answer text)
INTENT_CLASSIFICATION_PROMPT = """\
<intent_instructions>
Classify user query intent and task complexity. Reply with ONLY valid JSON matching the schema at the end.
Do not generate user-facing answers — routing fields only.
intent_type must be exactly one of: "continue_thread", "new_goal", "quiz".

Types (set unused text fields to null):
- quiz: greetings, thanks, fillers, pleasantries, static factual/trivia/definitions/simple math — only when answerable reliably from training knowledge without tools, files, web, or live data. task_complexity=minimal.
- continue_thread: follow-up on prior turns, results, or refinements. reuse_current_goal=true when active_goal exists, else false. task_complexity=medium.
- new_goal: needs tools/files/web/search/analysis/code, or a clear standalone assignment. goal_description: normalized, 5-15 words. friendly_message: friendly, action-oriented, 1-2 sentences. task_complexity minimal|simple|medium|complex where minimal=one direct answer without tools; simple=one focused execute step; medium=several steps or moderate tool use; complex=architecture, migration, broad refactor, or multi-phase work. Also new_goal when the user starts a fresh standalone task, repudiates or resets prior context, says to ignore earlier chat, or switches to an unrelated topic—use query wording, not only whether recent_conversation is non-empty.

NOT quiz (use new_goal instead):
- Real-time or time-sensitive queries: weather, news, stocks, sports scores, exchange rates, traffic, flight status, etc.
- Anything requiring web search, external APIs, attached files, code execution, or tools to answer correctly.
- Questions you cannot answer confidently from training knowledge alone.

Precedence (evaluate 1 before 2, and so on):
1. Explicit new standalone task OR user overrides/repudiates/resets prior context OR query is clearly unrelated to recent_conversation/active_goal topic (ignore earlier, unrelated topic, fresh assignment) -> new_goal
2. Greeting, thanks, small talk, or static factual question reliably answerable from training knowledge without tools -> quiz
3. References prior conversation or follow-up on recent results -> continue_thread
4. Needs tools/files/web/search/analysis OR cannot answer without tools OR uncertain -> new_goal

JSON schema:
{{
  "intent_type": "continue_thread"|"new_goal"|"quiz",
  "reuse_current_goal": boolean,
  "goal_description": string|null,
  "friendly_message": string|null,
  "task_complexity": "minimal"|"simple"|"medium"|"complex"
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
You are {assistant_name}. Re-classify intent. ONLY valid JSON per schema below. Routing only — no user-facing answer text.
intent_type: "continue_thread"|"new_goal"|"quiz". Set fields per type: quiz -> task_complexity minimal (static greetings/trivia only, no tools); continue_thread -> reuse_current_goal from active_goal, task_complexity medium; new_goal -> goal_description (5-15 words) + friendly_message (1-2 action-oriented sentences). task_complexity: minimal|simple|medium|complex.

NOT quiz: real-time/time-sensitive (weather, news, stocks, sports), web/tools/files needed, or not answerable from training knowledge alone -> new_goal.

Precedence: (1) new standalone, user ignores/resets prior, or unrelated to recent topic -> new_goal (2) greeting/thanks/static trivia without tools -> quiz (3) prior-turn follow-up -> continue_thread (4) tools needed, cannot answer without tools, or default -> new_goal.

JSON schema:
{{
  "intent_type": "continue_thread"|"new_goal"|"quiz",
  "reuse_current_goal": boolean,
  "goal_description": string|null,
  "friendly_message": string|null,
  "task_complexity": "minimal"|"simple"|"medium"|"complex"
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
