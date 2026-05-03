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
Classify this query's intent.

CRITICAL OUTPUT RULES:
- Return ONLY valid JSON matching the schema below
- "intent_type" MUST be exactly one of: "chitchat", "thread_continuation", "new_goal", "quiz"

Intent classification criteria:
- chitchat: Greetings, thanks, fillers, conversational pleasantries needing no action
  Examples: "hello", "你好", "thanks", "good morning"
  → Requires chitchat_response in detected user language (analyze query language)
  → task_complexity=chitchat

- quiz: Factual knowledge questions, trivia, definitions, simple math
  Examples: "What is the capital of France?", "Who wrote Romeo and Juliet?",
           "What's quantum entanglement?", "What is 15 * 23?"
  Detection: Question asking for known facts, no tools/files/analysis needed
  → quiz_response (brief factual answer from your knowledge, 1-3 sentences)
  → task_complexity=quiz

- thread_continuation: References prior conversation/results, follow-up actions, refinements
  Examples: "translate that", "explain the result", "continue from where we stopped", "refine the output"
  Detection: Analyze recent conversation context, look for references ("that", "this", "result", "output")
  → reuse_current_goal=true if active_goal exists, false otherwise
  → task_complexity=medium (follow-up actions)

- new_goal: Standalone tasks requiring tools (file ops, web search, analysis, coding)
  Examples: "analyze the codebase", "build authentication system",
           "search web for recent AI papers", "read config and extract settings"
  → goal_description required (normalized task description, 5-15 words)
          Example: "analyze the codebase"
  → friendly_message required (action-oriented reinterpretation, 1-2 sentences, friendly tone)
          Example: "I will read the project readme files and show the first 10 lines"
  → task_complexity=medium (default) or complex (architecture/migrations)
  → ALSO use new_goal when the user clearly starts a NEW standalone task, repudiates or
    resets prior context, asks to ignore earlier discussion, or switches topic to
    unrelated work—even if recent_conversation is non-empty. Judge intent from the
    query wording, not from the presence of prior turns alone.

Intent precedence (apply in order):
1. If the user explicitly starts a new standalone task OR repudiates / overrides prior
   context (ignore earlier, new topic unrelated to last turns, fresh assignment) → new_goal
2. If query is conversational filler (greeting/thanks) → chitchat
3. If query is factual knowledge question (no tools needed) → quiz
4. If query references prior conversation or is a follow-up on recent results → thread_continuation
5. If query requires tools/files/analysis → new_goal (DEFAULT when uncertain)

Required JSON shape:
{{
  "intent_type": "chitchat"|"thread_continuation"|"new_goal"|"quiz",
  "reuse_current_goal": boolean,
  "goal_description": string|null,
  "friendly_message": string|null,
  "task_complexity": "chitchat"|"quiz"|"medium"|"complex",
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
- "intent_type" MUST be exactly one of: "chitchat", "thread_continuation", "new_goal", "quiz"
- For "chitchat": set chitchat_response (detect user language from query)
- For "quiz": set quiz_response (brief factual answer)
- For "thread_continuation": set reuse_current_goal based on active_goal
- For "new_goal": set goal_description AND friendly_message (action-oriented reinterpretation)
- "task_complexity": chitchat | quiz | medium | complex
- "reasoning" is REQUIRED

Intent precedence:
1. Explicit new standalone task or user overrides / ignores prior context → new_goal
2. Conversational filler → chitchat
3. Factual knowledge question (no tools) → quiz
4. Prior-turn follow-up or refinement → thread_continuation
5. Tool-requiring task → new_goal (DEFAULT)

Required JSON shape:
{{
  "intent_type": "chitchat"|"thread_continuation"|"new_goal"|"quiz",
  "reuse_current_goal": boolean,
  "goal_description": string|null,
  "friendly_message": string|null,
  "task_complexity": "chitchat"|"quiz"|"medium"|"complex",
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

# Routing classification prompt
ROUTING_PROMPT = """\
You are {assistant_name}. Classify this request.
Current time: {current_time}
{conversation_context}
Request: {query}

CRITICAL OUTPUT RULES:
- Return ONLY valid JSON.
- "task_complexity" MUST be exactly one of: "chitchat", "medium", "complex".
- For "chitchat", provide a short friendly "chitchat_response" string in detected user language.
- For "medium" or "complex", set "chitchat_response" to null.
- Do not output placeholders, punctuation, comments, markdown, or extra keys.

Required JSON shape:
{{"task_complexity": "chitchat"|"medium"|"complex", "chitchat_response": string|null}}

Classification rules:
- chitchat: Greetings, thanks, fillers needing no action. Set chitchat_response in detected language.
- medium: Research, questions, tasks, debugging, follow-up actions. DEFAULT when uncertain.
- complex: Architecture design, large migrations, major refactoring.
"""

ROUTING_RETRY_PROMPT = """\
You are {assistant_name}. Re-classify this request.
Current time: {current_time}

Request: {query}

CRITICAL OUTPUT RULES:
- Return ONLY valid JSON.
- "task_complexity" MUST be exactly one of: "chitchat", "medium", "complex".
- For "chitchat", provide a short friendly "chitchat_response" string.
- For "medium" or "complex", set "chitchat_response" to null.
- Do not output placeholders, punctuation, comments, markdown, or extra keys.

Required JSON shape:
{{"task_complexity": "chitchat"|"medium"|"complex", "chitchat_response": string|null}}
"""
