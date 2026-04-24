"""LLM prompts for intent classification (IG-226, IG-250).

Structured prompts for LLM-driven intent classification with conversation context.
Pure LLM-driven - no keyword heuristics or language detection shortcuts.
"""

from __future__ import annotations

# Intent classification prompt (primary classification)
INTENT_CLASSIFICATION_PROMPT = """\
You are {assistant_name}. Classify this query's intent.

Current time: {current_time}
Thread ID: {thread_id}
Active goal: {active_goal_context}

Recent conversation:
{conversation_context}

Query: {query}

CRITICAL OUTPUT RULES:
- Return ONLY valid JSON matching the schema below
- "intent_type" MUST be exactly one of: "chitchat", "thread_continuation", "new_goal", "quiz"
- For "chitchat": set chitchat_response (short friendly reply in user's detected language)
- For "quiz": set quiz_response (brief factual answer from your knowledge)
- For "thread_continuation": set reuse_current_goal=true if active_goal exists
- For "new_goal": set goal_description (normalized task description, 5-15 words)
- "task_complexity" is secondary: chitchat | quiz | medium | complex
- "reasoning" is REQUIRED: brief explanation (1-2 sentences)
- Do not output placeholders, markdown, comments, or extra keys

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
  Examples: "count all readme files", "analyze the codebase", "build authentication system",
           "search web for recent AI papers", "read config and extract settings"
  → goal_description required (normalized task description, 5-15 words)
  → task_complexity=medium (default) or complex (architecture/migrations)

Intent precedence (apply in order):
1. If query references prior conversation (check conversation_context) → thread_continuation
2. If query is conversational filler (greeting/thanks) → chitchat
3. If query is factual knowledge question (no tools needed) → quiz
4. If query requires tools/files/analysis → new_goal (DEFAULT when uncertain)

Required JSON shape:
{{
  "intent_type": "chitchat"|"thread_continuation"|"new_goal"|"quiz",
  "reuse_current_goal": boolean,
  "goal_description": string|null,
  "task_complexity": "chitchat"|"quiz"|"medium"|"complex",
  "chitchat_response": string|null,
  "quiz_response": string|null,
  "reasoning": string
}}
"""

# Retry prompt (simplified, no conversation context)
INTENT_CLASSIFICATION_RETRY_PROMPT = """\
You are {assistant_name}. Re-classify this query's intent.

Current time: {current_time}
Active goal: {active_goal_context}

Query: {query}

CRITICAL OUTPUT RULES:
- Return ONLY valid JSON matching the schema
- "intent_type" MUST be exactly one of: "chitchat", "thread_continuation", "new_goal", "quiz"
- For "chitchat": set chitchat_response (detect user language from query)
- For "quiz": set quiz_response (brief factual answer)
- For "thread_continuation": set reuse_current_goal based on active_goal
- For "new_goal": set goal_description
- "task_complexity": chitchat | quiz | medium | complex
- "reasoning" is REQUIRED

Intent precedence:
1. Prior conversation reference → thread_continuation
2. Conversational filler → chitchat
3. Factual knowledge question (no tools) → quiz
4. Tool-requiring task → new_goal (DEFAULT)

Required JSON shape:
{{
  "intent_type": "chitchat"|"thread_continuation"|"new_goal"|"quiz",
  "reuse_current_goal": boolean,
  "goal_description": string|null,
  "task_complexity": "chitchat"|"quiz"|"medium"|"complex",
  "chitchat_response": string|null,
  "quiz_response": string|null,
  "reasoning": string
}}
"""

# Legacy routing prompt (backward compatible)
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
