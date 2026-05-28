"""LLM prompts for intent classification (IG-226, IG-250, IG-325, IG-363, IG-364).

Quiz-only classification: the LLM decides whether a query is a simple quiz
(greeting, thanks, static trivia answerable without tools) or requires the
agentic loop. The continue_thread vs new_goal distinction is now determined
structurally by the runner based on loop state, not by the classifier.

Prompt layout: static instructions and schema first; variable runtime fields
last inside flat XML structure (no nested wrappers).

XML structure:
- <intent_instructions>: Static content (classification rules, JSON schema)
- <intent_inputs>: Dynamic runtime fields as flat XML elements
  - <current_time>, <current_query>: Runtime context
"""

from __future__ import annotations

# Intent classification prompt (quiz detection only; continue/new_goal decided structurally)
INTENT_CLASSIFICATION_PROMPT = """\
<intent_instructions>
Classify whether the user query is a simple quiz or requires the agentic loop. Reply with ONLY valid JSON matching the schema below.
Do not generate user-facing answers — routing fields only.

intent_type must be exactly one of:
- "quiz": greetings, thanks, fillers, pleasantries, static factual/trivia/definitions/simple math — only when answerable reliably from training knowledge without tools, files, web, or live data.
- "agentic": everything else — needs tools/files/web/search/analysis/code, is a follow-up, or cannot be answered from training knowledge alone.

NOT quiz (use "agentic" instead):
- Real-time or time-sensitive queries: weather, news, stocks, sports scores, exchange rates, traffic, flight status, etc.
- Anything requiring web search, external APIs, attached files, code execution, or tools to answer correctly.
- Questions you cannot answer confidently from training knowledge alone.
- Follow-ups on prior conversation or work.

When intent_type is "agentic", also provide:
- goal_description: normalized, 5-15 words.
- friendly_message: friendly, action-oriented, 1-2 sentences.
- task_complexity: minimal|simple|medium|complex where minimal=one direct answer without tools; simple=one focused execute step; medium=several steps or moderate tool use; complex=architecture, migration, broad refactor, or multi-phase work.

JSON schema:
{{
  "intent_type": "quiz"|"agentic",
  "goal_description": string|null,
  "friendly_message": string|null,
  "task_complexity": "minimal"|"simple"|"medium"|"complex"
}}
</intent_instructions>

<current_time>{current_time}</current_time>

<current_query>
{query}
</current_query>
"""

# Retry prompt (simplified)
INTENT_CLASSIFICATION_RETRY_PROMPT = """\
<intent_instructions>
Re-classify intent. ONLY valid JSON per schema below. Routing only — no user-facing answer text.

intent_type: "quiz" (greeting/thanks/static trivia answerable without tools) or "agentic" (everything else).
NOT quiz: real-time/time-sensitive, web/tools/files needed, not answerable from training knowledge alone, or follow-ups → "agentic".

When "agentic": goal_description (5-15 words) + friendly_message (1-2 action-oriented sentences).
task_complexity: minimal|simple|medium|complex.

JSON schema:
{{
  "intent_type": "quiz"|"agentic",
  "goal_description": string|null,
  "friendly_message": string|null,
  "task_complexity": "minimal"|"simple"|"medium"|"complex"
}}
</intent_instructions>

<intent_inputs>
<current_time>{current_time}</current_time>
<current_query>
{query}
</current_query>
</intent_inputs>
"""
