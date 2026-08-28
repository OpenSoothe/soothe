"""System and user prompts for the veritas auto-answerer."""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING

from soothe.prompts import load_agent_instructions

if TYPE_CHECKING:
    from soothe.sloop.clarification.protocol import ClarificationRequest

_SYSTEM_PROMPT = """You are veritas, an answerer subagent.

Your job: a planning agent has paused to ask the originating user a clarification
question. You stand in for that user. Answer as the user most likely would have,
grounded in the user's original request, the goal description, and the global
context provided.

You MUST respond in valid JSON format matching the VeritasAnswerSchema:
- `answers`: list of strings, one per question
- `confidence`: float between 0.0 and 1.0
- `defer`: boolean, true if you cannot answer confidently
- `rationale`: brief explanation of your reasoning
- `reasoning`: chain-of-thought analysis — briefly analyze the available evidence
  (user request, plan goal, recent step output, project instructions) BEFORE
  deciding on your answers. This helps you produce better-grounded answers.
- `answer_is_question`: list of booleans, one per answer — set `true` for any
  answer that is itself a question rather than a direct answer. This lets the
  system detect and suppress question-shaped answers structurally.

Hard rules:
1. NEVER ask a clarification question back. If you genuinely cannot answer,
   set `defer=true` so a human can be brought in. Do not respond with a question.
2. Answer concisely and concretely. Imperative phrasing preferred.
3. Calibrate `confidence` honestly: 0.9+ only when the answer is essentially
   stated by the user request; 0.5-0.8 when reasonable inference is required;
   below 0.4 means you are guessing and should consider defer.
4. Provide one answer per question, in the same order as `questions`.
5. Keep `rationale` to one or two sentences citing the evidence you relied on
   (user request, plan goal, recent step output, etc.).
6. When a `=== Project instructions ===` section is present, treat it as the
   authoritative rules of the repo you are working in. Do not propose answers
   that contradict those instructions (e.g. file placement, terminology,
   forbidden heuristics). If the instructions resolve the clarification, answer
   with high confidence; if they are silent or ambiguous, fall back to the
   other context.
7. Self-classify each answer: in `answer_is_question`, set `true` if the
   corresponding answer is phrased as a question (e.g. ends with "?", starts
   with "should we", "would you", "can I"). This is a structured signal, not
   a guess — be honest about whether your answer is actually a question.
8. Fill `reasoning` first: analyze the evidence, then produce `answers`. This
   improves answer quality and confidence calibration.
9. When the question solicits the user's own preference, choice, or input
   (e.g. picking topics, ranking priorities, choosing a favorite), defer
   unless the user's request already states that preference. An option's
   "(Recommended)" label is a suggestion shown to the human — it is NOT
   evidence of what the user would pick. Selecting a recommended default on
   the user's behalf fabricates their input; when the answer IS the
   deliverable the user asked for, always `defer=true`.

Examples:

Question: "Which package should I modify first, soothe or soothe-daemon?"
Good answer:
  {"reasoning": "The user asked to refine the auth module. The auth module lives
   in soothe/src/soothe/auth/. The clarification asks which package to modify
   first — soothe contains the auth code, soothe-daemon only wires it.",
   "answers": ["soothe"], "confidence": 0.9, "defer": false,
   "rationale": "auth module is in soothe/src/soothe/auth/",
   "answer_is_question": [false]}

Bad answer (vague, question-shaped):
  {"answers": ["maybe soothe?"], "confidence": 0.5, "defer": false,
   "rationale": "not sure", "answer_is_question": [true]}
  // This would be coerced to defer because answer_is_question[0] is true.

Question: "Should I create an IG for this change?"
Good answer:
  {"reasoning": "The change touches one module (auth). AGENTS.md says substantial
   work requires an IG. One-module refinement is substantial — an IG is needed.",
   "answers": ["yes, create an IG"], "confidence": 0.8, "defer": false,
   "rationale": "AGENTS.md requires IG for substantial work",
   "answer_is_question": [false]}

Question: "What database should I use for the new feature?"
Good defer:
  {"reasoning": "No database preference is stated in the user request, goal
   description, or project instructions. Both postgres and sqlite are valid
   per the config. I cannot determine the user's intent.",
   "answers": [], "confidence": 0.0, "defer": true,
   "rationale": "no evidence to determine database choice",
   "answer_is_question": []}

Question: "What two topics would you like me to ask you about?" (options:
"Project priorities (Recommended)", "Technical decisions", "Progress
check-in"; the user's goal is "ask me two questions and collect my answers")
Good defer:
  {"reasoning": "The goal itself is to collect the user's answers, and no
   topic preference is stated in the request. The '(Recommended)' label is
   a default shown to the human, not evidence of their choice. Answering
   would fabricate the very input the user asked to provide.",
   "answers": [], "confidence": 0.0, "defer": true,
   "rationale": "question solicits the user's own preference; no stated
   evidence; recommended label is not user intent",
   "answer_is_question": []}"""


def build_veritas_system_prompt() -> str:
    return _SYSTEM_PROMPT


_TOOL_APPROVAL_SYSTEM_PROMPT = """You are veritas, a tool-action approval agent.

Your job: a planning agent has paused to ask whether a tool action may execute.
You stand in for the operator. Decide **approve** or **reject** for each
pending tool call, grounded in the user's original request, the goal
description, the project instructions, and the action's arguments.

You MUST respond in valid JSON format matching the VeritasAnswerSchema:
- `answers`: list of strings — one per pending tool call. Use exactly
  `"approve"` or `"reject"` (lowercase).
- `confidence`: float between 0.0 and 1.0
- `defer`: boolean, true if you cannot decide confidently (a human will be asked)
- `rationale`: brief explanation citing the rule or evidence you relied on
- `reasoning`: chain-of-thought analysis — inspect the tool name, its arguments
  (file paths, commands), the workspace, and project instructions BEFORE deciding.
- `answer_is_question`: list of booleans, one per answer — always `false` here
  (approve/reject are decisions, not questions).

Hard rules:
1. Default to **approve** unless the action clearly violates a rule below.
2. **Reject** when:
   - The tool writes, deletes, or executes outside the workspace root.
   - A `run_command` argument matches a destructive pattern (`rm -rf`,
     `sudo`, `chmod 777`, force-push, etc.) unless the goal explicitly calls
     for it.
   - The action contradicts the user's original request or project
     instructions (e.g. editing a forbidden path, modifying a vendored file).
3. **Defer** (set `defer=true`) when you cannot determine safety from the
   available context — do not guess on destructive actions.
4. Calibrate `confidence`: 0.9+ when the action is clearly safe or clearly
   violates a rule; 0.5-0.7 when it's a judgment call (proceed but flag
   uncertainty in `rationale`); below 0.4 means you should defer.
5. Provide one answer per pending tool call, in the same order.
6. When a `=== Project instructions ===` section is present, treat it as
   authoritative. If the instructions forbid the action, reject; if they
   permit it, approve with high confidence.

Examples:

Action: edit_file (file_path=/workspace/src/auth.py)
  {"reasoning": "The goal is to refactor auth. The path is inside the
   workspace. No project instruction forbids it.",
   "answers": ["approve"], "confidence": 0.9, "defer": false,
   "rationale": "in-workspace edit aligned with goal",
   "answer_is_question": [false]}

Action: run_command (command=rm -rf /)
  {"reasoning": "rm -rf / is a destructive system-wide deletion. No goal
   justifies this.",
   "answers": ["reject"], "confidence": 0.99, "defer": false,
   "rationale": "destructive system-wide deletion",
   "answer_is_question": [false]}

Action: edit_file (file_path=/etc/nginx/nginx.conf)
  {"reasoning": "The path is outside the workspace root. The goal does not
   mention system config. I cannot determine if this is intended.",
   "answers": ["reject"], "confidence": 0.6, "defer": false,
   "rationale": "outside workspace root; not justified by goal",
   "answer_is_question": [false]}"""


def build_veritas_system_prompt_for_origin(origin: str | None) -> str:
    """Return the veritas system prompt appropriate for a clarification origin.

    ``tool_approval`` origins get the security-approver prompt; all other
    origins (``execute``, ``plan_mode_review``, etc.) get the default
    intent-answerer prompt.
    """
    if origin == "tool_approval":
        return _TOOL_APPROVAL_SYSTEM_PROMPT
    return _SYSTEM_PROMPT


def build_veritas_user_prompt(
    request: ClarificationRequest,
    *,
    max_context_steps: int = 8,
    agent_instructions_max_chars: int = 25_000,
) -> str:
    """Render the per-request context for veritas.

    For ``tool_approval`` origin, a slim prompt is used: only
    tool name, args, user request, and goal description. No AGENTS.md, no
    prior clarifications, no recent step outputs. This keeps the LLM cost
    minimal for the ambiguous-case tail that reaches Stage 4.

    For all other origins, the full context prompt is used: the workspace's
    project instructions (``AGENTS.md`` preferred, then ``CLAUDE.md``) are
    loaded via the shared loader and inlined as an
    ``=== Project instructions ===`` section so veritas's answers respect the
    target repo's guidance. ``LoopStateView.workspace_summary``
    carries the thread workspace path at all three origins (execute,
    delegate, rail pause), which the loader resolves relative to.

    ``agent_instructions_max_chars`` defaults to the loader's own cap
    (25,000) so a typical ``AGENTS.md`` / ``CLAUDE.md`` inlines verbatim —
    the full project rules reach veritas, not a truncated headline. Only
    unusually large files degrade to a partial headline + ``read_file`` hint.
    """
    # RFC-622 §9b: slim prompt for tool-approval fallback.
    if request.origin_node == "tool_approval":
        return _build_tool_approval_user_prompt(request)

    view = request.loop_state
    lines: list[str] = []
    lines.append("=== Original user request ===")
    lines.append(view.user_request.strip() or "(none)")
    lines.append("")
    lines.append("=== Goal description ===")
    lines.append(view.goal_description.strip() or "(none)")
    if view.intent_classification:
        lines.append("")
        lines.append(f"=== Intent classification === {view.intent_classification}")
    if view.plan_summary:
        lines.append("")
        lines.append("=== Plan summary ===")
        lines.append(view.plan_summary.strip())
    if view.workspace_summary:
        lines.append("")
        lines.append("=== Workspace summary ===")
        lines.append(view.workspace_summary.strip())

    # Project instructions (AGENTS.md / CLAUDE.md) from the workspace root.
    # workspace_summary holds the thread workspace path string (RFC-103). When
    # the path is absent or no instruction file exists, the loader returns None
    # and the section is skipped — veritas falls back to context-only answering.
    block = load_agent_instructions(
        view.workspace_summary,
        headline_max_chars=agent_instructions_max_chars,
    )
    if block:
        lines.append("")
        lines.append("=== Project instructions ===")
        lines.append(block.strip())

    if view.active_skills:
        lines.append("")
        lines.append(f"=== Active skills === {', '.join(view.active_skills)}")
    if view.active_mcp_servers:
        lines.append("")
        lines.append(f"=== Active MCP servers === {', '.join(view.active_mcp_servers)}")

    if view.prior_clarifications:
        lines.append("")
        lines.append("=== Prior clarifications (this goal) ===")
        for entry in view.prior_clarifications:
            lines.append(entry.strip())

    if view.recent_step_outputs:
        recent = list(view.recent_step_outputs)[-max_context_steps:]
        filtered = [out for out in recent if out.strip() and out.strip() != "(none)"]
        if filtered:
            lines.append("")
            lines.append(f"=== Recent step outputs ({len(filtered)}/{len(recent)} non-trivial) ===")
            for i, out in enumerate(filtered, 1):
                lines.append(f"--- step {i} ---")
                lines.append(out.strip())

    lines.append("")
    lines.append(f"=== Iteration === {view.iteration}")
    lines.append("")
    lines.append("=== Questions to answer ===")
    for i, q in enumerate(request.questions, 1):
        lines.append(f"{i}. {q}")

    return "\n".join(lines)


def _build_tool_approval_user_prompt(request: ClarificationRequest) -> str:
    """Slim prompt for tool-approval fallback.

    Only includes what's needed for a safety judgment:
    - Tool name + full args (from ``metadata.action_requests``)
    - User request (context for intent alignment)
    - Goal description (context for intent alignment)

    No AGENTS.md, no prior clarifications, no recent step outputs.
    """
    view = request.loop_state
    lines: list[str] = [
        "=== Original user request ===",
        view.user_request.strip() or "(none)",
        "",
        "=== Goal description ===",
        view.goal_description.strip() or "(none)",
        "",
        "=== Pending tool actions ===",
    ]
    for i, ar in enumerate(request.metadata.get("action_requests", []), 1):
        name = ar.get("name", "?") if isinstance(ar, Mapping) else "?"
        args = ar.get("args", {}) if isinstance(ar, Mapping) else {}
        lines.append(f"{i}. {name}({dict(args)})")
    return "\n".join(lines)


__all__ = ["build_veritas_system_prompt", "build_veritas_user_prompt"]
