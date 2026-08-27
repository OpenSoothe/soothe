# RFC-622: CoreAgent Clarification Relay

**RFC**: 622
**Title**: CoreAgent Clarification Relay
**Status**: Implemented
**Kind**: Architecture Design
**Created**: 2026-06-02
**Authors**: Soothe Team
**Updated**: 2026-08-27
**Depends on**: RFC-220 (Agentic Goal Execution / StrangeLoop), RFC-222 (Autopilot Mode), RFC-600 (Plugin Extension System), RFC-601 (Built-in Agents), RFC-403 (Unified Event Naming)
**Supersedes**: Empty-answer auto-resume behavior currently encoded in `sloop/engine/graph_interrupt.py::build_auto_resume_payload` for `type=="ask_user"` interrupts.
**Revisions**: [2026-08-27](#changelog) — §9c Structured ask_user schema + `StructuredAskUserWidget`; §2.1, §4.2, §4.3, §5.1, §6, §10, §15, §17 updated. | [2026-08-27](#changelog) — §9b Multi-stage tool-approval pipeline; §2.1, §4.2, §4.3, §6, §12 updated.

---

## 1. Abstract

When the **CoreAgent** (deepagents-based LangGraph) emits a clarification — e.g. *"What specific area or aspect of Soothe would you like to refine?"* — the surrounding **StrangeLoop** silently auto-resumes the interrupt with empty-string answers. The model receives no useful input, replans into a spin, and burns iterations.

This RFC introduces a **clarification relay**: a `ClarificationPolicy` protocol, a dedicated `await_clarification` graph node in the StrangeLoop, two built-in policies (interactive TUI relay and auto-answer), a new `veritas` subagent that answers clarifications as the originating user would, and a TUI Manual/Auto mode toggle. The pause-on-human path is durable via the existing LangGraph checkpointer.

The relay works identically in solo StrangeLoop and autopilot runs **without** forcing `GoalEngine` into solo mode: policy is injected through `LoopRuntimeContext`.

---

## 2. Scope

### 2.1 In scope

- `ClarificationPolicy` protocol and two built-in implementations.
- `await_clarification` StrangeLoop graph node and routing changes.
- `LoopGraphState` additions for pending clarification + answer + origin.
- `veritas` subagent (intent-grounded auto-answerer) under `subagents/veritas/`.
- TUI Manual ↔ Auto toggle, status badge, and `--mode` CLI flag.
- Detection of structured `ask_user` LangGraph interrupts. Plain-text questions in assistant messages are intentionally **not** detected; callers that want to ask the user must emit a structured interrupt.
- **Structured `ask_user` schema (§9c)**: the `ask_user` tool accepts `list[QuestionSpec]` — each with title, description, exactly 3 options (short + long), and a recommended index. The CLI renders a `StructuredAskUserWidget` with tab navigation, hover-preview option selection, a 4th custom free-text row, and a persistent Submit/Abandon footer. Applies to the generic (execute) render path only; HITL plan-review and tool-approval modes are untouched.
- New goal status `awaiting_clarification` and a CLI/API to answer deferred clarifications out-of-band.
- New event types `soothe.loop.clarification_*` and `soothe.subagent.veritas.*`.
- `agent.clarification.*` and `agent.veritas.*` configuration additions in both `config/config.template.yml` and `config/develop/nano.yml`.
- **Multi-stage tool-approval pipeline** (§9b): deterministic deny → safety → allow stages resolve most `tool_approval` interrupts without an LLM; veritas remains the final guard for ambiguous cases. Config: `agent.clarification.tool_approval.*`.

### 2.2 Non-goals

- Action-approval HITL (`type=="review"` interrupts) — current auto-approve behavior is preserved.
- Cross-loop or cross-goal clarifications.
- Operator dashboard UI beyond CLI events.
- Restructuring LangGraph interrupt primitives or `deepagents.HumanInTheLoopMiddleware`.
- Rule persistence / TUI "always allow" button (future work; the pipeline uses static config rules only).
- Sandboxing (separate concern from approval gating).
- Structured-option support for HITL plan-review and tool-approval modes (§9c applies to the generic execute path only; a future RFC may unify HITL modes).

---

## 3. Motivation

| Issue (current behavior) | Relay response |
|--------------------------|----------------|
| `ask_user` interrupts auto-resumed with `""` answers (`graph_interrupt.py:47`) | Policy-driven payload from real human or auto-answerer |
| StrangeLoop has no graph state for "paused on human" | First-class `pending_clarification` state + dedicated node |
| Solo StrangeLoop has no GoalEngine; autopilot does | `ClarificationPolicy` protocol injected via `LoopRuntimeContext`; runtimes pick their implementation |
| No way for an operator to see/answer questions out-of-band | `awaiting_clarification` goal status + `soothe goal answer` CLI |
| Plain-text clarifications (no tool call, no `interrupt`) silently end turns | Heuristic detector synthesizes an equivalent request |

The bug is reproducible in trace `trace-2626ed6b65d86c80845248e42f383bff.json`: three consecutive `plan_generate`/`plan_assess` cycles produce empty model outputs after the model asks *"What specific area or aspect of Soothe would you like to refine?"*.

---

## 4. Architecture

### 4.1 Component overview

```
                          ┌─────────────────────────────┐
   CoreAgent.astream()    │ Stream wrapper:              │
   inside execute /       │  _core_agent_astream_with_   │
   plan_generate /        │  interrupt_resume            │
   plan_assess            └─────────────┬───────────────┘
                                        │
                          ┌─────────────┴───────────────┐
                          │ ClarificationDetector        │
                          │ - structured ask_user only   │
                          └─────────────┬───────────────┘
                                        │
                               set state.pending_clarification
                                        │
                                        ▼
                          ┌─────────────────────────────┐
                          │ StrangeLoop graph router       │
                          │ short-circuits to:           │
                          │   await_clarification        │
                          └─────────────┬───────────────┘
                                        │
                          ┌─────────────────────────────┐
                          │ await_clarification node     │
                          │ → ClarificationPolicy        │
                          └─────────────┬───────────────┘
                          ┌─────────────┴───────────────┐
                          ▼                              ▼
            InteractiveClarificationPolicy   AutoClarificationPolicy
                  (TUI relay,                   (veritas subagent;
                   loop-level interrupt,         defer if low confidence)
                   durable checkpoint)
                          │                              │
                          └─────────────┬───────────────┘
                                        │
                        state.pending_clarification_answer
                                        │
                          ┌─────────────▼───────────────┐
                          │ route_after_clarification    │
                          │ → originating node           │
                          └─────────────┬───────────────┘
                                        │
                          CoreAgent resumed with
                          Command(resume={"answers": [...]})
```

### 4.2 New components

| Component | Path | Responsibility |
|-----------|------|----------------|
| `ClarificationPolicy` protocol | `sloop/clarification/protocol.py` | Abstract interface; request/answer dataclasses |
| `InteractiveClarificationPolicy` | `sloop/clarification/interactive.py` | TUI relay; loop-level `interrupt(...)` for durability |
| `AutoClarificationPolicy` | `sloop/clarification/auto.py` | Delegates to `veritas`; enforces min-confidence; raises `ClarificationDeferred`; short-circuits `tool_approval` via pipeline (§9b) |
| `ClarificationDetector` | `sloop/clarification/detector.py` | Recognizes structured `ask_user` and `action_requests` interrupts; populates `metadata` |
| `await_clarification` node | `sloop/orchestrator/nodes/await_clarification.py` | Calls policy; emits audit events; updates state |
| `veritas` subagent | `subagents/veritas/{__init__,events,implementation,prompts,schemas}.py` | Intent-grounded auto-answerer; structured output via Pydantic |
| `ToolApprovalPipeline` | `sloop/clarification/tool_approval_pipeline.py` | Multi-stage deny → safety → allow evaluator; defers ambiguous to veritas (§9b) |
| `ToolApprovalRule` matcher | `sloop/clarification/tool_rule_matcher.py` | Command (exact/prefix/wildcard) + path (gitignore-style) pattern matching |
| `ToolSafetyCheck` | `sloop/clarification/tool_safety_check.py` | Bypass-immune dangerous-path/file/command checker |
| `StructuredAskUserWidget` | `cli/tui/widgets/messages/structured_ask_user.py` | Structured multi-question option-picker widget for generic (execute) ask_user (§9c) |
| `QuestionSpec` / `OptionSpec` | `coreagent/tools/ask_user.py` | Pydantic models for structured ask_user args (§9c) |

### 4.3 Changed components

| File | Change |
|------|--------|
| `sloop/engine/graph_interrupt.py` | Drop empty-answer default for `ask_user`; helpers stay |
| `sloop/engine/executor.py` | `_core_agent_astream_with_interrupt_resume` returns to node on `ask_user` instead of auto-resuming; resumes with real payload on re-entry |
| `sloop/orchestrator/builder.py` | Add `await_clarification` node + edges |
| `sloop/orchestrator/routing.py` | Each `route_after_*` short-circuits to `await_clarification` if `pending_clarification` is set |
| `sloop/orchestrator/state.py` | Add `pending_clarification`, `pending_clarification_answer`, `last_clarification_origin` |
| `sloop/orchestrator/runtime_context.py` | Add `clarification_policy: ClarificationPolicy` |
| `core/goal_engine/*` | Add `awaiting_clarification` status + `answer_clarification(goal_id, ...)` API |
| `cli/tui/app/_messages_mixin.py` | `ctrl+m` action; mode status badge |
| `cli/main.py` | `--mode {manual,auto}` flag plumbed to runtime |
| `config/config.template.yml`, `config/develop/nano.yml` | New `agent.clarification.*` and `agent.veritas.*` sections; `agent.clarification.tool_approval.*` sub-block (§9b) |
| `sloop/clarification/protocol.py` | `ClarificationRequest` gains optional `metadata` field; `ClarificationAnswer.source` gains `"static"` literal (§9b) |
| `sloop/clarification/detector.py` | `from_tool_approval_interrupt` populates `metadata={"action_requests": [...]}` (§9b) |
| `sloop/clarification/auto.py` | `AutoClarificationPolicy` gains `tool_approval_pipeline` init arg; short-circuit branch in `answer()` for `tool_approval` origin (§9b) |
| `sloop/clarification/selector.py` | `build_default_clarification_policy` passes `tool_approval_pipeline` through (§9b) |
| `sloop/clarification/runtime_factory.py` | Builds pipeline from config; dual-model wiring (think for intent, fast for tool-approval fallback) (§9b) |
| `subagents/veritas/prompts.py` | `build_veritas_user_prompt` gains slim variant for `tool_approval` origin (§9b) |
| `config/models.py` | `ClarificationConfig` gains `tool_approval: ToolApprovalConfig` sub-block (§9b) |
| `coreagent/tools/ask_user.py` | `_AskUserArgs.questions` changes from `list[str]` to `list[QuestionSpec]`; `question`/`query` singular aliases dropped; validators enforce 3 options, recommended range, title/desc word limits (§9c) |
| `cli/tui/widgets/messages/clarification.py` | `_compose_generic`, `_finalize`, `_on_input_submitted` generic path, and generic-mode CSS deleted; `ClarificationInputMessage` now only renders option-selector (HITL) modes (§9c) |
| `cli/tui/textual_adapter.py` | `_mount_manual_clarification_input` routes by payload shape: structured `QuestionSpec` dicts → `StructuredAskUserWidget`; plain strings → degraded free-text shim (§9c) |

---

## 5. Data Flow

### 5.1 Flow 1: Interactive clarification (Manual mode)

1. CoreAgent emits `interrupt({"type":"ask_user", "questions":[QuestionSpec(...), ...]})` inside `execute`. Each question carries a title (≤3 words), description (≤100 words), exactly 3 options (each with `short` + `long`), and a `recommended` index (§9c).
2. Stream wrapper sees the chunk, sets `state.pending_clarification` and `state.last_clarification_origin = "execute"`, exits the stream loop without auto-resume.
3. `execute` node returns; `route_after_execute` detects `pending_clarification` and routes to `await_clarification`.
4. `await_clarification` calls `InteractiveClarificationPolicy.answer(request)`, which:
   - Emits `soothe.loop.clarification_requested`.
   - Calls LangGraph `interrupt(loop_request)` at the loop level → checkpoint snapshotted.
   - Blocks until `Command(resume=...)` is supplied by the TUI.
5. TUI shows a modal with the questions; on submit, the TUI client sends a `Command(resume=…)` to the loop graph.
6. `await_clarification` receives the answer, sets `state.pending_clarification_answer`, clears `state.pending_clarification`, emits `soothe.loop.clarification_answered`.
7. `route_after_clarification` reads `last_clarification_origin` and routes back to `execute`.
8. `execute` re-enters; stream wrapper sees `pending_clarification_answer`, constructs `Command(resume={origin_interrupt_id: {"answers": [...]}})`, calls `CoreAgent.astream(Command(resume=…))`, clears the answer field.
9. CoreAgent continues from where it paused.

### 5.2 Flow 2: Auto clarification (Auto mode)

Steps 1–3 identical to Flow 1.

4. `await_clarification` calls `AutoClarificationPolicy.answer(request)`, which:
   - Invokes `veritas` with the request, the first-principles slice (original user goal, intent classification, plan goal_description), and global context (workspace summary, recent step outputs, active skills/MCP).
   - Receives `VeritasAnswerSchema(answers, confidence, defer, rationale)`.
   - If `defer == True` or `confidence < auto_min_confidence`, raises `ClarificationDeferred(reason)`.
   - Otherwise returns `ClarificationAnswer(source="veritas", ...)`.
5. On success, steps 6–9 identical to Flow 1.
6. On `ClarificationDeferred`: `await_clarification` calls `ctx.mark_goal_status("awaiting_clarification", reason=…)`, emits `soothe.loop.clarification_deferred`, returns `terminate=True`. Loop stops. Goal is later resumed by `soothe goal answer <id> "..."` or autopilot scheduler when an answer arrives.

### 5.3 No plain-text fallback

Plain assistant text that asks a question is **not** detected. The relay
engages only when CoreAgent (or one of its middlewares) emits a structured
`interrupt({"type": "ask_user", ...})`. Callers that want a clarification
must use the structured form; this keeps the relay surface deterministic and
avoids false positives on assistant text that legitimately ends with a
rhetorical or summarizing question.

---

## 6. Abstract Schemas

### 6.1 `ClarificationRequest`

```
ClarificationRequest {
  questions: list[QuestionSpec | Text]   # structured (§9c) or plain-string (degraded)
  origin_node: Enum("execute", "plan_mode_review", "rail_pause", "tool_approval")
  origin_interrupt_id: ID
  loop_state_snapshot: LoopStateView   # read-only projection of LoopGraphState
  metadata: Map[Text, Any] = {}        # origin-specific payload; §9b
}
```

The `metadata` field carries the raw interrupt payload for origin-specific
consumers. For `tool_approval`, it holds `{"action_requests": [...]}` so the
pipeline (§9b) can inspect tool names and args directly. Empty for other
origins. Default `{}` — backward compatible with pre-§9b serialized state.

`questions` is `list[QuestionSpec]` for generic (execute) `ask_user`
interrupts (§9c). HITL origins (`plan_mode_review`, `tool_approval`) still
carry plain-string questions — their render path is unchanged. The
degraded fallback (§9c) handles in-flight plain-string questions from before
the schema upgrade.

### 6.1a `QuestionSpec` and `OptionSpec` (§9c)

```
OptionSpec {
  short: Text          # ≤12 words — answer label shown in recap, sent on resume
  long: Text           # 1–3 sentences — shown in hover-preview box
}

QuestionSpec {
  title: Text          # ≤3 words — tab label for question navigation
  description: Text    # ≤100 words — shown under the tab
  options: list[OptionSpec]   # exactly 3
  recommended: Int     # 0–2 (index into options); -1 = no recommendation
}
```

The 4th "custom" option (free-text answer) is **implicit** — the widget
always renders it as a 4th row; the model does not emit it. On resume,
each answer is either the selected option's `short` text or the custom
free-text. `_format_answers` uses `QuestionSpec.title` for the `Q:` line
(falls back to `str(q)` for plain-string backward compat).

### 6.2 `ClarificationAnswer`

```
ClarificationAnswer {
  answers: list[Text]                   # parallel to request.questions
  source: Enum("human", "veritas", "fallback", "static")
  confidence: Float | Null              # auto answers only
  defer: Bool                           # signal to pause goal
  audit: Map[Text, Any]
}
```

`source="static"` marks decisions resolved by the deterministic pipeline
stages (§9b), distinguishing them from LLM (`veritas`) and human (`human`)
decisions in the audit trail and prior-clarifications context.

### 6.3 `VeritasAnswerSchema`

```
VeritasAnswerSchema {
  answers: list[Text]
  confidence: Float in [0.0, 1.0]
  defer: Bool
  rationale: Text                       # short explanation for audit
}
```

### 6.4 `LoopGraphState` additions

```
LoopGraphState {
  …existing fields…
  pending_clarification: ClarificationRequest | Null
  pending_clarification_answer: ClarificationAnswer | Null
  last_clarification_origin: Enum("execute", "plan_generate", "plan_assess") | Null
}
```

### 6.5 Goal status enum addition

```
GoalStatus = Enum(
  …existing values…,
  "awaiting_clarification"               # NEW
)
```

---

## 7. Architectural Constraints

1. **Solo and autopilot share one policy abstraction.** `GoalEngine` is not introduced into the solo loop. `LoopRuntimeContext.clarification_policy` is the single injection point.
2. **Pause-on-human is checkpointable.** `InteractiveClarificationPolicy` uses LangGraph `interrupt(...)` at the loop graph level so the loop's existing checkpointer captures it. TUI restart / daemon restart resumes cleanly.
3. **Veritas never asks back.** Its system prompt forbids emitting clarifications; any clarification-shaped output is coerced to `defer=True`. No recursive clarification.
4. **Confidence floor is a safety net.** Even if veritas omits `defer`, `AutoClarificationPolicy` enforces `auto_min_confidence` and defers on low-confidence answers.
5. **Auto-approve preserved.** Action-approval interrupts (`type=="review"`) keep their current auto-approve path; this RFC does not touch them.
6. **Reentrant state (IG-760).** The `pending_clarification` channel is the re-entry contract: everything needed to resume (plan draft, path, refinement comments, origin) MUST be serialized into this graph channel before parking, so a fresh worker can reconstruct context via `aget_state`. The CE goal status `awaiting_clarification` is the source of truth for parking — `resolve_clarification_resume_ce_goal` matches both `"active"` and `"awaiting_clarification"` goals so a worker crash during plan-mode review doesn't lose the parked state. Cancel ≠ terminal: a cancel during a long-running operation (synthesis, refinement) cancels the in-flight LLM call, not the goal's clarification status. See IG-760 for the full design.
6. **Detection is structured-only.** Only `ask_user` LangGraph interrupts are detected. Plain-text questions in assistant messages are not treated as clarifications, eliminating heuristic false positives.
7. **Mode toggle is hot-swappable.** Changing Manual ↔ Auto in the TUI replaces the policy for *future* requests; in-flight requests complete under the previous policy.

---

## 8. Loop Graph Topology

### 8.1 Delta (RFC-220)

New node and edges added to `build_strange_loop_graph` (current topology defined in RFC-220 §4).

```
execute             → route_after_execute       → {record_iteration, await_clarification, END}
plan_generate       → route_after_plan          → {goal_completion, resolve_decision, await_clarification}
plan_assess         → route_after_assess        → {goal_completion, resolve_decision, plan_generate, await_clarification}
await_clarification → route_after_clarification → {execute, plan_generate, plan_assess, END}
```

`route_after_clarification` uses `state.last_clarification_origin`; `END` is only reached when policy raises `ClarificationDeferred`.

### 8.2 Routing rule

Each `route_after_*` checks `state.pending_clarification` first; if set, returns `"await_clarification"` regardless of other state. This keeps the per-node routing logic compositional and isolates the clarification short-circuit to one check.

---

## 9. Veritas Subagent

### 9.1 Role

A thin, fast subagent that answers clarifications **as the originating user would**, grounded in:

- **First-principles slice**: original user request text, intent classification, top-level `plan.goal_description`. Execution noise is excluded.
- **Global context**: workspace tree summary, last `max_context_steps` step outputs, active skills, active MCP servers, policy denials so far.

It is **not** a CoreAgent. It is a single structured-output LLM call backed by `config.create_chat_model("clarification")` (new role; defaults to the `plan_assess` model when unconfigured).

### 9.2 Module layout

```
subagents/veritas/
├── __init__.py
├── events.py           # register_event for soothe.subagent.veritas.*
├── implementation.py   # answer(request, runtime) → VeritasAnswerSchema
├── prompts.py          # system prompt enforcing no-clarification, intent voice
└── schemas.py          # VeritasAnswerSchema (Pydantic)
```

### 9.3 Wire events

| Event | Payload |
|-------|---------|
| `soothe.subagent.veritas.requested` | `question_count`, `origin_node` |
| `soothe.subagent.veritas.answered` | `confidence`, `defer`, `rationale_preview` |
| `soothe.subagent.veritas.deferred` | `reason`, `confidence` |

All registered through `register_event(...)` (RFC-600).

---

## 9b. Multi-Stage Tool-Approval Pipeline

### 9b.1 Problem

In auto mode, every `tool_approval` interrupt triggers a full veritas LLM
call: `think`-class model, ~25k-char user prompt (AGENTS.md inlined verbatim,
recent step outputs, prior clarifications), structured-output enforcement,
up to 2 retries. Most decisions are trivially safe (in-workspace `edit_file`)
or trivially dangerous (`rm -rf /`, editing `.git/config`). An LLM is not
needed for these. The cost is both latency (round-trip per tool call) and
token spend (huge prompt × every interrupt × every goal), especially severe
in autopilot runs.

### 9b.2 Pipeline

Borrowed from Claude Code's layered permission system: deterministic stages
first, LLM classifier as the last resort. The pipeline runs for the
`tool_approval` origin only; all other origins are untouched.

```
tool_approval interrupt
        │
        ▼
Stage 1: Deny rules          ── deterministic, instant
  (denylist command patterns, forbidden paths)
  → match ──► REJECT (source="static")
        │ no match
        ▼
Stage 2: Safety checks       ── bypass-immune, instant
  (DANGEROUS_FILES, DANGEROUS_DIRECTORIES, path traversal,
   UNC paths, destructive command patterns)
  → match ──► REJECT (source="static")
        │ no match
        ▼
Stage 3: Allow rules         ── deterministic, instant
  (allowlist command patterns, in-workspace writes)
  → match ──► APPROVE (source="static")
        │ no match
        ▼
Stage 4: Veritas LLM         ── final guard, ambiguous cases only
  (slim prompt: tool name, args, user request, goal —
   no AGENTS.md, no step outputs; fast model)
  → APPROVE / REJECT / DEFER (source="veritas")
```

**First stage that returns a decision wins.** Stages 1–3 are microsecond,
no-LLM. Stage 4 is the existing veritas path with a slimmer prompt and
`fast` model role.

The deny-first ordering is a security property: a destructive command
pattern is rejected before any allow rule can fire. Safety checks are
bypass-immune — they run regardless of config, like Claude Code's
`checkPathSafetyForAutoEdit` which blocks `.git/` and shell configs even in
`bypassPermissions` mode. Allow rules never override safety. The LLM is
the final guard, not the first.

### 9b.3 New components

| Component | Path | Responsibility |
|-----------|------|----------------|
| `ToolApprovalRule` matcher | `sloop/clarification/tool_rule_matcher.py` | Command (exact/prefix `:*`/wildcard `*`) + path (gitignore-style via `pathspec`) pattern matching |
| `ToolSafetyCheck` | `sloop/clarification/tool_safety_check.py` | `DANGEROUS_FILES`/`DANGEROUS_DIRECTORIES`/`DESTRUCTIVE_COMMAND_PATTERNS` — bypass-immune, not configurable |
| `ToolApprovalPipeline` | `sloop/clarification/tool_approval_pipeline.py` | Multi-stage evaluator; returns `ApprovalResult` or `None` (defer to veritas) |

### 9b.4 Built-in safety constants

```python
DANGEROUS_FILES = frozenset({
    ".gitconfig", ".gitmodules",
    ".bashrc", ".bash_profile",
    ".zshrc", ".zprofile", ".profile",
    ".ripgreprc",
    ".mcp.json", ".claude.json",
})

DANGEROUS_DIRECTORIES = frozenset({
    ".git", ".vscode", ".idea", ".claude",
})

DESTRUCTIVE_COMMAND_PATTERNS = (
    "rm -rf", "rm -r", "rm -f",
    "sudo", "chmod 777", "chmod -R",
    "git push --force", "git push -f",
    "dd if=", "mkfs", "shred",
)
```

These are built-in constants, not configurable per-rule, because they
represent bypass-immune security boundaries (same principle as Claude
Code's `DANGEROUS_FILES` / `DANGEROUS_DIRECTORIES`).

### 9b.5 `AutoClarificationPolicy` short-circuit

```python
async def answer(self, request: ClarificationRequest) -> ClarificationAnswer:
    # NEW: tool-approval pipeline short-circuit (§9b)
    if (request.origin_node == "tool_approval"
            and self._tool_approval_pipeline is not None):
        action_requests = request.metadata.get("action_requests", [])
        result = self._tool_approval_pipeline.evaluate(
            action_requests,
            workspace_root=request.loop_state.workspace_summary,
        )
        if result is not None:
            return ClarificationAnswer(
                answers=(result.decision,),
                source="static",
                confidence=1.0,
                audit={"stage": result.stage, "reason": result.reason},
            )
        # fall through to veritas (existing path)

    # existing: requires_manual check, veritas call, fallback logic
    ...
```

### 9b.6 Veritas fallback prompt truncation

When a case reaches Stage 4, the user prompt is drastically slimmer — only
what is needed for a safety judgment:

- Tool name + full args (from `metadata.action_requests`)
- User request (context for intent alignment)
- Goal description (context for intent alignment)

**No** AGENTS.md inline, **no** prior clarifications, **no** recent step
outputs. Model role is `fast` (not `think`). The slim variant is gated on
origin inside `build_veritas_user_prompt`.

### 9b.7 Workspace resolution

`workspace_root` is per-request (from `LoopStateView.workspace_summary`),
not per-goal. The pipeline is constructed without a workspace root; the
workspace is resolved at evaluation time from the `ClarificationRequest` and
passed to `match_path_rule`. If `workspace_summary` is `None`, path-based
allow rules do not fire — everything reaches veritas (fail-safe).

### 9b.8 Safety properties

1. **Deny rules first.** Destructive commands rejected before any allow rule.
2. **Safety checks bypass-immune.** `.git/` and shell configs always blocked, regardless of allow rules or config.
3. **Allow rules never override safety.** Pipeline order guarantees safety (Stage 2) runs before allow rules (Stage 3).
4. **Fail-safe on pipeline error.** Any exception in Stages 1–3 → `None` → veritas. Never auto-approve on error.
5. **Fail-safe on workspace unknown.** `workspace_summary is None` → path-based allow rules don't fire → veritas.
6. **Veritas remains the final guard.** Ambiguous cases still get LLM scrutiny.
7. **`delete` is never auto-approved by default.** Default allow rules include `edit_file`/`write_file` but not `delete`. Operators can add a `delete` allow rule explicitly.

### 9b.9 Expected impact

For a typical autopilot goal with 20 tool calls (mostly in-workspace
`edit_file` + safe `run_command` like `pytest`):

| Stage | Calls | LLM? | Cost |
|-------|------:|------|------|
| 1. Deny rules | 0 | no | ~0 |
| 2. Safety checks | ~2 | no | ~0 |
| 3. Allow rules | ~16 | no | ~0 |
| 4. Veritas LLM | ~2 | yes (fast, ~500-token prompt) | minimal |
| **Before** | 20 | all yes (think, ~25k-token prompt) | **huge** |

~90% of tool approvals become instant and free.

### 9b.10 Out of scope for §9b

- Changing `interrupt_on` wiring in `coreagent/builder.py` (still interrupts on all 4 mutating tools — the pipeline decides faster, the interrupt surface is unchanged).
- Applying the pipeline to non-`tool_approval` origins.
- Rule persistence / TUI "always allow" button (future work).
- Sandboxing (separate concern).
- Caching across tool calls within a goal (future optimization).

---

## 9c. Structured `ask_user` Schema and Widget

### 9c.1 Problem

The `ask_user` tool accepts `questions: list[str]` — plain text only. The CLI
(`ClarificationInputMessage`) renders a single free-text `Input` per question
in generic mode. The model has no way to offer the user structured choices
(options with short/long descriptions, a recommended pick, a custom
fallback). For decision-gate questions that don't rise to HITL plan review or
tool approval (e.g. "which auth method?", "Redis or Postgres for the token
store?"), the user must type a full answer instead of picking from suggested
options.

### 9c.2 Schema

The `ask_user` tool args change from `list[str]` to `list[QuestionSpec]`:

```python
class OptionSpec(BaseModel):
    short: str   # ≤12 words — answer label, shown in recap, sent on resume
    long: str    # 1–3 sentences — shown in hover-preview box

class QuestionSpec(BaseModel):
    title: str           # ≤3 words — tab label
    description: str     # ≤100 words — shown under the tab
    options: list[OptionSpec]  # exactly 3
    recommended: int     # 0–2 (index into options); -1 = no recommendation

class _AskUserArgs(BaseModel):
    questions: list[QuestionSpec]
```

**Validators:**
- `OptionSpec.short`: ≤12 words (whitespace-split count).
- `OptionSpec.long`: non-empty, 1–3 sentences.
- `QuestionSpec.title`: ≤3 words.
- `QuestionSpec.description`: ≤100 words.
- `QuestionSpec.options`: exactly 3 entries (reject if ≠3).
- `QuestionSpec.recommended`: in `[-1, 2]` (reject if out of range).
- `_AskUserArgs._normalize`: strip empty/invalid question entries; reject if
  none survive. The `question`/`query` singular aliases are dropped —
  structured questions can't be expressed as a single string.

### 9c.3 Wire protocol

**Host → CLI** (interrupt payload):
```json
{
  "type": "ask_user",
  "questions": [
    {
      "title": "Auth method",
      "description": "How should the API authenticate requests?",
      "options": [
        {"short": "OAuth 2.0", "long": "OAuth 2.0 with PKCE. Best for browser flows."},
        {"short": "API key", "long": "Static API key in a header. Simplest to implement."},
        {"short": "Session", "long": "Server-side session with cookies. Best for SSR apps."}
      ],
      "recommended": 0
    }
  ]
}
```

**CLI → host** (resume payload, unchanged format):
```json
{"answers": ["OAuth 2.0", "Redis", "custom text…"]}
```

Each entry is the selected option's `short` text, or the custom free-text.
`_format_answers` uses `QuestionSpec.title` for the `Q:` line (falls back to
`str(q)` for plain-string backward compat).

### 9c.4 Widget: `StructuredAskUserWidget`

New widget at `cli/tui/widgets/messages/structured_ask_user.py`. Replaces the
generic (execute) free-text render path. `ClarificationInputMessage` loses
its `_compose_generic` path and now only renders HITL option-selector modes.

**Layout:**

```
┌─ Tab bar ──────────────────────────────────────────────┐
│ ✓ Q1   ✓ Q2   ▸Q3                                      │
├─────────────────────────────────────────────────────────┤
│  Title: "Retry policy"                                  │
│  Description: "How should we handle transient           │
│  failures in the message consumer?"                     │
│                                                         │
│  ▸ 1. Exponential backoff (recommended)                 │
│    ┌─────────────────────────────────────────┐          │
│    │ Double the delay each retry, up to 60s. │          │
│    │ Best for network hiccups and rate limits.│          │
│    └─────────────────────────────────────────┘          │
│    2. Fixed delay                                       │
│    3. Circuit breaker                                   │
│    4. Custom: [_____________________________]           │
├─────────────────────────────────────────────────────────┤
│  2/3 answered            [Submit]  [Abandon]            │
│  ←/→ questions  ↑/↓ options  Enter select  Tab footer   │
└─────────────────────────────────────────────────────────┘
```

**Tab bar:** one tab per question. Tabs show `✓` when answered; active tab
shows `▸`. Titles are `QuestionSpec.title` (≤3 words). Hidden when only one
question (no siblings to switch between; ←/→ are no-ops).

**Option list:** 3 model-provided options + a 4th "Custom" row with an inline
`Input`. The recommended option shows "(recommended)". ↑/↓ cycles all 4 rows.
The highlighted option's `long` description expands in a bordered preview box;
unhighlighted options show only their `short` label.

**Custom row:** when highlighted, the inline `Input` is enabled and focusable.
Typing text + Enter finalizes the custom answer for that question. Selecting
custom with empty text blocks submit (shows hint).

**Footer:** persistent bar with `N/M answered` count + `[Submit]` (disabled
until all answered) + `[Abandon]`. Reachable via `Tab` from any question.
When Submit is pressed, an inline recap block renders above the footer:

```
  Review:
    Q1: Auth method  → OAuth 2.0
    Q2: Token store  → Redis
    Q3: Retry policy → Exponential backoff

  [Submit]  [Abandon]
```

Enter on Submit finalizes; Enter on Abandon cancels (posts `Submitted` with
empty answers → `_format_answers` returns dismissal text → model gets
"Clarification dismissed without an answer. Decide how to proceed.").

**Answered state (per question):** the selected option row is bold/success-
colored. The user can navigate back and change the selection — nothing is
final until Submit.

**Submitted state (final):** the widget collapses to a summary view: each
question title + selected answer (parity with `ClarificationInputMessage`'s
`is-submitted` answered view). Tabs, options, and footer are hidden.

**`Submitted` message:** `StructuredAskUserWidget` defines its own
`Submitted(Message)` — it does not reuse `ClarificationInputMessage.Submitted`.
The two widgets serve disjoint wire contracts.

### 9c.5 Keybindings

| Key | Action | Scope |
|-----|--------|-------|
| ← | Previous question tab | Question area |
| → | Next question tab | Question area |
| ↑ | Highlight previous option | Question area |
| ↓ | Highlight next option | Question area |
| Enter | Select highlighted option (or finalize custom text) | Question area |
| Tab | Move focus to footer (Submit → Abandon → back to question) | Anywhere |
| Esc | Abandon | Anywhere |

←/→ in this widget switch questions, **not** cycle options. This differs
from `ClarificationInputMessage` where ←/→ cycle the 3 HITL actions. The two
widgets have disjoint keybinding semantics because they serve disjoint wire
contracts — no conflict since only one is mounted at a time.

### 9c.6 CLI routing

```python
def _build_clarification_widget(payload):
    questions = payload.get("questions", [])
    if questions and isinstance(questions[0], dict) and "options" in questions[0]:
        return StructuredAskUserWidget(
            questions=questions, step_id=payload["step_id"], ...)
    # Degraded fallback: plain-string questions from old in-flight interrupts.
    return StructuredAskUserWidget(
        questions=questions, step_id=payload["step_id"], ..., degraded=True)
```

In degraded mode, the widget renders one free-text `Input` per question + a
simple Submit button — no tabs, no options, no hover-preview. This is a narrow
shim, not a maintained second mode; once the model is upgraded, this path is
dead.

### 9c.7 Error handling

- **Model emits ≠3 options** → `QuestionSpec` validator rejects with
  `ValueError` → tool error returned to model for retry.
- **`recommended` out of range** → validator rejects → model retries.
- **Title >3 words or description >100 words** → validator rejects → model
  retries.
- **Custom selected but empty text** → widget blocks submit, shows "Enter a
  custom answer or pick an option" hint inline.
- **Submit before all questions answered** → Submit button disabled (grey,
  not focusable).
- **Abandon** → posts `Submitted` with empty answers → `_format_answers`
  returns dismissal text → model gets "Clarification dismissed without an
  answer. Decide how to proceed."

### 9c.8 Out of scope for §9c

- HITL plan-review and tool-approval modes stay in `ClarificationInputMessage`
  untouched. Their HITL wire decode contract (`Approve`/`Refine`/`Reject` →
  `decision` types) is unchanged.
- Structured-option support for HITL modes (future RFC; requires host decoder
  to map selected options back to `decision` types).
- Dual-write / wire migration period — the host tool is upgraded in one
  commit; the CLI widget lands in the same release. Interrupts are ephemeral,
  not persisted as structured records.

---

## 10. TUI Mode Toggle

| Aspect | Behavior |
|--------|----------|
| Keybind | `ctrl+m` toggles Manual ↔ Auto. Shift+Tab is retained for the loop selector. |
| Status badge | `[manual]` (green) or `[auto]` (yellow) on the persistent status line. |
| CLI flag | `soothe --mode {manual,auto}` for one-shot runs. Default: `manual` when stdin is a TTY, `auto` otherwise. |
| Autopilot | Ignores the flag. Always Auto. |
| Hot swap | Replaces `LoopRuntimeContext.clarification_policy` for future requests. In-flight requests complete under the prior policy. |
| Modal | Manual mode shows a modal with the question(s); submit sends `Command(resume=…)` to the loop graph. |
| Structured widget (§9c) | Generic (execute) `ask_user` renders as `StructuredAskUserWidget`: tabs for multi-question navigation (←/→), ↑/↓ highlight with inline long-desc preview, Enter selects, 4th custom free-text row, persistent footer with Submit/Abandon + inline recap before final submit. HITL plan-review and tool-approval keep their existing 3-button selector. |

---

## 11. Events

New event types (registered via RFC-600 `register_event`):

| Event | Payload | Owner |
|-------|---------|-------|
| `soothe.loop.clarification_requested` | `questions`, `origin_node`, `mode` | `sloop/clarification/events.py` |
| `soothe.loop.clarification_answered` | `source`, `confidence`, `defer` | same |
| `soothe.loop.clarification_deferred` | `reason`, `question_summary` | same |
| `soothe.subagent.veritas.requested` | `question_count`, `origin_node` | `subagents/veritas/events.py` |
| `soothe.subagent.veritas.answered` | `confidence`, `defer`, `rationale_preview` | same |
| `soothe.subagent.veritas.deferred` | `reason`, `confidence` | same |

---

## 12. Configuration

```yaml
agent:
  clarification:
    auto_policy: veritas              # only built-in for now
    auto_min_confidence: 0.4          # below this, treat as defer
    max_defer_age_hours: 168          # autopilot: scrub stale awaiting_clarification goals
    default_mode: auto                # wire may override per turn (auto|manual)
    force_manual_origins:             # never veritas-auto these origins
      - planner_subagent_review       # planner *subagent* gate only (RFC-633)
                                      # NOT StrangeLoop plan_generate/plan_assess

    # §9b: Multi-stage tool-approval pipeline
    tool_approval:
      enabled: true                    # master switch; false = all tool_approval go to veritas
      deny_rules:                      # Stage 1: match = immediate REJECT
        - { tool: run_command, pattern: "rm -rf *" }
        - { tool: run_command, pattern: "sudo *" }
        - { tool: run_command, pattern: "chmod 777 *" }
        - { tool: run_command, pattern: "git push --force*" }
        - { tool: run_command, pattern: "git push -f*" }
        - { tool: run_command, pattern: "dd if=*" }
        - { tool: run_command, pattern: "mkfs*" }
        - { tool: edit_file, pattern: "/etc/**" }
        - { tool: write_file, pattern: "/etc/**" }
      # Stage 2: safety checks are built-in, bypass-immune (not configurable).
      #          See §9b.4 for the constant lists.
      allow_rules:                      # Stage 3: match = immediate APPROVE
        - { tool: edit_file, pattern: "<workspace>/**" }
        - { tool: write_file, pattern: "<workspace>/**" }
        - { tool: run_command, pattern: "ls *" }
        - { tool: run_command, pattern: "cat *" }
        - { tool: run_command, pattern: "grep *" }
        - { tool: run_command, pattern: "find *" }
        - { tool: run_command, pattern: "pytest*" }
        - { tool: run_command, pattern: "python -m pytest*" }
        - { tool: run_command, pattern: "ruff *" }
        - { tool: run_command, pattern: "mypy *" }
        - { tool: run_command, pattern: "git status" }
        - { tool: run_command, pattern: "git diff*" }
        - { tool: run_command, pattern: "git log*" }
      veritas_fallback:                 # Stage 4: LLM for ambiguous cases
        enabled: true
        model_role: fast               # use fast model, not think
        max_context_steps: 0           # no recent step outputs in prompt
        inline_project_instructions: false  # no 25k AGENTS.md
      audit:
        log_decisions: true
        log_level: info

  veritas:
    model_role: think                  # reuses existing ModelRole
    max_context_steps: 8
```

`force_manual_origins` keeps selected clarification origins on the interactive
TUI relay even when the turn's clarification mode is `auto`. The default is
**planner subagent review only** (`planner_subagent_review`). That gate is
unrelated to StrangeLoop planning-stage nodes `plan_generate` /
`plan_assess`. Other wired specialists (`browser_use`, `deep_research`, …)
are not listed and can still use veritas under auto mode. Headless / autopilot
runs (no human attached) defer forced origins instead of auto-answering. Empty
the list to allow veritas to answer every origin under auto mode.

The `tool_approval` sub-block (§9b) configures the multi-stage pipeline. When
`enabled: true`, deterministic deny → safety → allow stages resolve most
`tool_approval` interrupts without an LLM call; veritas remains the final
guard for ambiguous cases. When `enabled: false`, all `tool_approval`
interrupts go directly to veritas (pre-§9b behavior). Pattern syntax:
`exact` (literal match), `prefix:*` (prefix match), `wildcard*` (wildcard
match). Path patterns support `**` recursive matching via `pathspec`. The
`<workspace>` token expands to the per-request workspace root from
`LoopStateView.workspace_summary`.

Per project rule, both `config/soothe.template.yml` and the packaged
`soothe-daemon` setup template are updated in the same change.

---

## 13. Persistence and Out-of-Band Answers

- `awaiting_clarification` goal status is persisted by the goal-engine backend (autopilot) and by `StrangeLoopStateManager` (solo).
- New CLI: `soothe goal answer <goal_id> [--question-index N] "answer text"` writes the answer into the goal's pending-clarification record and clears `awaiting_clarification`.
- Autopilot scheduler treats `awaiting_clarification` as blocked: it does not count toward active-goal concurrency and is not selected for execution until cleared.
- TTL: goals stuck in `awaiting_clarification` longer than `max_defer_age_hours` are surfaced for operator review (autopilot only).

---

## 14. Integration Points

| External System | Integration Type | Data Exchange |
|-----------------|------------------|----------------|
| LangGraph checkpointer | API | Loop-level `interrupt(...)` snapshots loop state including pending clarification |
| TUI client | Event + Command | `clarification_requested` event → modal → `Command(resume=…)` |
| GoalEngine (autopilot) | API | `mark_goal_status("awaiting_clarification", …)`, `answer_clarification(...)` |
| `soothe` CLI | New command | `soothe goal answer <id> "..."` |
| Langfuse / observability | Events | All `clarification_*` and `veritas.*` events flow through the standard event bus |

---

## 15. Testing Strategy (informative)

Unit:
- `tests/unit/core/loop/clarification/test_protocol.py`
- `tests/unit/core/loop/clarification/test_interactive.py`
- `tests/unit/core/loop/clarification/test_auto.py`
- `tests/unit/core/loop/clarification/test_detector.py`
- `tests/unit/core/loop/orchestrator/stages/test_await_clarification.py`
- `tests/unit/core/loop/orchestrator/test_routing.py` (extended)
- `tests/unit/subagents/veritas/test_implementation.py`
- `tests/unit/core/loop/engine/test_graph_interrupt.py` (rewritten — assert policy dispatch, not empty answers)
- `tests/unit/core/loop/clarification/test_tool_rule_matcher.py` — exact, prefix, wildcard, path patterns (§9b)
- `tests/unit/core/loop/clarification/test_tool_safety_check.py` — dangerous files/dirs, path traversal, destructive commands (§9b)
- `tests/unit/core/loop/clarification/test_tool_approval_pipeline.py` — stage ordering, mixed batch, fail-safe, workspace unknown (§9b)
- `tests/unit/core/loop/stations/execute/test_tool_approval_bridge.py` (extended — pipeline short-circuit, source="static", slim prompt variant)
- `tests/unit/coreagent/test_ask_user_tool.py` (extended — `QuestionSpec`/`OptionSpec` validation: 3 options, recommended range, title/desc word limits, empty rejection; `_format_answers` with `QuestionSpec` title extraction) (§9c)
- `tests/unit/cli/tui/widgets/test_structured_ask_user.py` — compose, ←/→/↑/↓ navigation, Enter selection, custom Input flow, Submit recap, Abandon, submitted collapsed view, degraded path (§9c)

Integration:
- `tests/integration/sloop/test_clarification_relay.py` — full round-trip.
- `tests/integration/sloop/test_clarification_durable_pause.py` — checkpoint restart with pending clarification.

---

## 16. Migration & Risk

- **Behavior change**: solo CLI no longer silently empty-answers `ask_user`. Manual mode now blocks for input; Auto mode now calls veritas. This is the intended fix but a visible behavior delta.
- **Test impact**: `build_auto_resume_payload` tests rewritten. Action-approval auto-approve is preserved.
- **Veritas wrongness**: every answer emits an audit event with question + answer + source + confidence + rationale; below-threshold confidence forces defer.
- **Durability**: relies on StrangeLoop checkpointer (default-on); doctor check confirms presence.
- **Autopilot scheduler**: must recognize `awaiting_clarification` as blocked, not active — one-line change in concurrency accounting.

---

## 17. Open Items (deferred to Implementation Guide)

- ~~Concrete shape of the structured `ask_clarification` marker / tool (vs. relying on the existing `interrupt` shape only).~~ **Resolved by §9c**: the `ask_user` tool now accepts `list[QuestionSpec]` with title, description, 3 options (short + long), and recommended index. The CLI renders `StructuredAskUserWidget`.
- Migration of persisted goal-status enums for already-running autopilot instances.
- Whether `--mode auto` should fall back to TUI relay if `veritas` is not configured, or error out at startup.
- Exact workspace-trust interaction for veritas's filesystem summarization (RFC-621).
- Unifying HITL plan-review and tool-approval modes under `StructuredAskUserWidget` (future RFC; the host decoder must map selected options back to HITL `decision` types).

---

## 18. Related Documents

- [RFC Standard](./templates/rfc-standard.md)
- [RFC Index](./rfc-index.md)
- [RFC-220](./RFC-220-langgraph-agent-loop-orchestrator.md) — StrangeLoop topology that this RFC extends
- [RFC-222](./RFC-222-autopilot-goal-engine-architecture.md) — Autopilot scheduler whose status enum gains `awaiting_clarification`
- [RFC-600](./RFC-600-plugin-extension-system.md) — `register_event` used for new event types
- [RFC-601](./RFC-601-built-in-agents.md) — Built-in subagent registry that gains `veritas`
- [RFC-403](./RFC-403-unified-event-naming.md) — Event naming for `soothe.loop.clarification_*` and `soothe.subagent.veritas.*`
- Design draft: `docs/archive/drafts/2026-06-02-clarification-relay-design.md`
- Bug trace: `trace-2626ed6b65d86c80845248e42f383bff.json`

---

## Changelog

### 2026-08-27 (Revised — §9c Structured ask_user schema + widget)
- **§9c added**: `ask_user` tool args change from `list[str]` to `list[QuestionSpec]` (title ≤3 words, description ≤100 words, exactly 3 options with short+long, recommended index). New `StructuredAskUserWidget` in the CLI with tab navigation (←/→), hover-preview option selection (↑/↓ + Enter), 4th custom free-text row, persistent Submit/Abandon footer with inline recap. Applies to generic (execute) render path only; HITL plan-review and tool-approval modes untouched.
- **§2.1 scope** extended: structured schema + widget added to in-scope.
- **§2.2 non-goals** extended: HITL structured-option support explicitly out of scope (future RFC).
- **§4.2 components** extended: `StructuredAskUserWidget`, `QuestionSpec`/`OptionSpec` added.
- **§4.3 changed components** extended: `ask_user.py` (schema + validators), `clarification.py` (generic path deleted), `textual_adapter.py` (routing by payload shape).
- **§5.1 flow** updated: interrupt payload now carries `QuestionSpec` objects.
- **§6.1** `ClarificationRequest.questions` now `list[QuestionSpec | Text]`.
- **§6.1a** `QuestionSpec`/`OptionSpec` schemas added.
- **§10 TUI** extended: structured widget row added.
- **§15 testing** extended: `test_ask_user_tool.py` (schema validation), `test_structured_ask_user.py` (widget navigation).
- **§17 open items**: first item (structured marker shape) resolved by §9c; HITL unification added as future RFC.
- Design draft: `docs/drafts/2026-08-27-structured-ask-user-widget-design.md`

### 2026-08-24 (Revised — RFC-623 robustness)
- `veritas` migrated onto `invoke_structured_chat` shared helper.
- Dynamic per-request JSON Schema (`build_veritas_response_schema`) enforces "exactly N answers or defer" structurally.
- `DeferKind` taxonomy attached to `ClarificationDeferredError` and event payload.
- Interactive fallback (`InteractiveClarificationPolicy`) wired when veritas fails (`structured_output_failed`) and a human is attached.
- `tool_approval` origin added to `CLARIFICATION_ORIGINS`; default `force_manual_origins` excludes it so safe tool calls auto-approve via veritas's security-approver prompt.
- See RFC-623 for the full robustness specification.

### 2026-08-27 (Revised — §9b Multi-stage tool-approval pipeline)
- **§9b added**: deterministic deny → safety → allow pipeline for `tool_approval` origin. Stages 1–3 resolve most tool-approval interrupts without an LLM; veritas remains the final guard (Stage 4) with a slim prompt and `fast` model role.
- **§2.1 scope** extended: pipeline + config added to in-scope.
- **§2.2 non-goals** extended: rule persistence / TUI "always allow" and sandboxing explicitly out of scope.
- **§4.2 components** extended: `ToolApprovalPipeline`, `ToolApprovalRule` matcher, `ToolSafetyCheck` added.
- **§4.3 changed components** extended: `protocol.py` (`metadata`, `"static"`), `detector.py` (populates `metadata`), `auto.py` (pipeline short-circuit), `selector.py`, `runtime_factory.py` (dual-model wiring), `prompts.py` (slim variant), `config/models.py` (`ToolApprovalConfig`).
- **§6.1** `ClarificationRequest` gains `metadata: Map[Text, Any] = {}` field.
- **§6.2** `ClarificationAnswer.source` gains `"static"` literal.
- **§12 config** extended: `agent.clarification.tool_approval.*` sub-block with deny_rules, allow_rules, veritas_fallback, audit.
- **§15 testing** extended: `test_tool_rule_matcher.py`, `test_tool_safety_check.py`, `test_tool_approval_pipeline.py`, extended `test_tool_approval_bridge.py`.
- Design draft: `docs/drafts/2026-08-27-tool-approval-pipeline-design.md`
- Pattern reference: Claude Code `utils/permissions/` (`permissions.ts`, `filesystem.ts`, `shellRuleMatching.ts`, `dangerousPatterns.ts`).
