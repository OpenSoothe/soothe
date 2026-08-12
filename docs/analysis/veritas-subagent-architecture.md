# Veritas subagent architecture — components, interactions, and design patterns

> Scope: the **Veritas** auto-clarification subagent and its sole consumer
> (`AutoClarificationPolicy`) within the StrangeLoop clarification relay
> (RFC-622 / RFC-623 / IG-737). This is an architecture analysis, not a spec.

Related:
- RFC-622 — clarification relay contract
- RFC-623 — Veritas auto-mode robustness (structured-output boundary, glitch guards)
- IG-737 — `pause_for_user` rail → Veritas auto-clarification in autopilot
- `docs/analysis/subagents-inventory-soothe-and-deepagents.md` — how *every* subagent is
  reached via the `task` tool. **Veritas is NOT reached that way** — see §1 below.

---

## 1. What Veritas is (and is not)

Veritas is the **auto-answerer** for `ClarificationRequest`s produced by StrangeLoop.
It is **not** a deepagents subagent registered under the `task` tool. Unlike
`general-purpose` / `planner` / `deep_research`, Veritas is invoked **directly as a
Python function** by `AutoClarificationPolicy`, never by the model dispatching a
`subagent_type`. This is the key architectural distinction:

| Subagent class | Dispatch | Caller |
|----------------|----------|--------|
| deepagents-style (`general-purpose`, planner, …) | `task` tool, model-picked `subagent_type` | CoreAgent loop |
| **Veritas** | direct `await veritas.answer(request)` | `AutoClarificationPolicy` |

Consequence: Veritas has no `runnable`/`name` registration in `SubAgentMiddleware`,
no `task`-tool description, and no `subagent_type` string. Its contract is a typed
function, not a LangGraph node.

---

## 2. Components

### 2.1 Package layout (owned package `soothe`)

```
packages/soothe/src/soothe/
├── subagents/veritas/
│   ├── __init__.py          # lazy export of `answer`
│   ├── implementation.py    # answer(): prompt build → structured invoke → coerce
│   ├── prompts.py           # build_veritas_system_prompt / build_veritas_user_prompt
│   └── schemas.py           # VeritasAnswerSchema, build_veritas_response_schema(N),
│                            #   coerce_veritas_response
└── sloop/clarification/
    ├── protocol.py          # ClarificationRequest, ClarificationAnswer, DeferKind
    ├── detector.py          # ClarificationDetector (origin capture)
    ├── origins.py           # force_manual_origins set, resume_node map
    ├── selector.py          # build_default_clarification_policy(mode=...)
    └── auto.py              # AutoClarificationPolicy (sole Veritas consumer)
```

DAG compliance: `soothe` imports `soothe_nano.utils.llm.*` (invoke policy, structured
output) and `soothe_sdk.observability.langfuse` — no reverse arrows into
`soothe_daemon` / `soothe_cli`.

### 2.2 `answer()` — the single entry point

`veritas.answer(request: ClarificationRequest) -> VeritasAnswerSchema` (async) is
the entire surface. Internals:

1. `prompts.build_veritas_system_prompt()` — static rules, incl. "never ask a
   question back".
2. `prompts.build_veritas_user_prompt(request.loop_state)` — inlines LoopStateView
   sections: original request, goal, intent, plan summary, workspace summary,
   **project instructions** (`load_agent_instructions` → `AGENTS.md`/`CLAUDE.md`,
   capped at 25k chars), active skills/MCP, recent step outputs, iteration, and the
   questions themselves.
3. `schemas.build_veritas_response_schema(n)` — a **`oneOf` JSON schema** enforced at
   the structured-output call boundary: exactly *N non-empty answers* **OR** a single
   `defer`. This rejects wrong-count / empty answers before any Python post-check.
4. `soothe_nano.utils.llm.invoke_structured_chat(...)` wrapped in
   `await_with_llm_call_policy(...)` for rate-limit handling; optional Langfuse
   `RunnableConfig` traces the span under the parent loop graph
   (`_build_traced_invoke_config`).
5. `schemas.coerce_veritas_response(data, n)` — fills missing metadata when the model
   returns answers-only JSON; `VeritasAnswerSchema.model_validate(data)` enforces
   field constraints after coercion.
6. **Glitch guards** (RFC-623):
   - `StructuredOutputError` → forced defer, `rationale="structured_output_failed: ..."`.
   - Any answer ending in `?` → forced defer, `rationale="answer_was_question"`.

### 2.3 `AutoClarificationPolicy` — the sole consumer

`selector.build_default_clarification_policy(mode=...)` returns:
- `mode="manual"` → `InteractiveClarificationPolicy` (human-in-the-loop, durable
  LangGraph `interrupt`).
- `mode="auto"` → `AutoClarificationPolicy` (autopilot, or any run with no human
  wired).

`AutoClarificationPolicy.answer(request)`:
1. **Origin guard** — `requires_manual(origin_node)` against `force_manual_origins`.
   Forced origins skip Veritas and go to `interactive_fallback` (if wired) or raise
   `ClarificationDeferredError(kind="explicit")`.
2. **Veritas call** — injected `veritas_answer` fn (default `veritas.answer`).
3. **Classify** — `_classify(result)` maps result → `DeferKind | None` (see §3.3).
4. **Interactive fallback** (RFC-623) — when `kind == "structured_output_failed"` and
   an `interactive_fallback` is wired (interactive runs only), delegate to it via
   `answer_as_manual_fallback` instead of terminating. Autopilot has no human → keeps
   hard-defer.
5. **Resolve** — accepted result → `ClarificationAnswer{answers, source="veritas",
   confidence, defer=False, audit}`; the loop resumes CoreAgent with it. Defer raises
   `ClarificationDeferredError(kind=...)` → `awaiting_clarification` goal status →
   terminates until answered out-of-band (`soothe goal answer ...`).

### 2.4 Rail integration (IG-737)

`pause_for_user` rails (`then: pause_for_user`) route through the same clarification
relay with origin `rail_pause`:

| Veritas outcome | CE root | Rail `suspended` | Rail event |
|-----------------|---------|------------------|-----------|
| PROCEED (confidence ≥ min) | unchanged | false | `user_intervention` |
| PAUSE / deny | suspended | true | (none) |
| defer / error / kill-switch / no config | suspended | true | (none) |

Kill-switch: `agent.autopilot.rail_pause_auto_clarify` (default `true`).
`rail_pause` is **not** in `force_manual_origins`, so Veritas always gets a chance.

---

## 3. Interactions

### 3.1 End-to-end flow (auto mode)

```
CoreAgent ask_user / trailing question / pause_for_user rail
   │
   ▼
ClarificationDetector → ClarificationRequest{questions, origin_node,
                                              origin_interrupt_id, loop_state}
   │
   ▼
selector.build_default_clarification_policy(mode)
   │  (mode=auto)
   ▼
AutoClarificationPolicy.answer(request)
   ├─ force_manual_origins guard ── (forced) ──► interactive_fallback / raise
   ├─ veritas.answer(request)
   │     ├─ build_veritas_system_prompt / user_prompt(LoopStateView)
   │     ├─ build_veritas_response_schema(n)  [oneOf: N answers XOR defer]
   │     ├─ invoke_structured_chat  ← await_with_llm_call_policy
   │     ├─ coerce_veritas_response → VeritasAnswerSchema.model_validate
   │     └─ glitch guards: StructuredOutputError / "?"-answer → forced defer
   ├─ _classify(result) → DeferKind | None
   │     ├─ rationale prefix "structured_output_failed:" → that kind
   │     ├─ rationale prefix "answer_was_question"       → that kind
   │     ├─ defer=True                                    → "explicit"
   │     ├─ confidence < min_confidence (0.4)             → "low_confidence"
   │     └─ else                                          → None (accept)
   ├─ (kind="structured_output_failed" & interactive_fallback wired) ──► fallback
   └─ accept → ClarificationAnswer{source="veritas"}  OR  raise ClarificationDeferredError(kind)
```

### 3.2 Manual-mode symmetry

In `mode="manual"`, the same `ClarificationRequest` is surfaced to a human via a
durable LangGraph `interrupt`. `InteractiveClarificationPolicy` is the
`interactive_fallback` target that `AutoClarificationPolicy` can delegate to on
structured-output failure (RFC-623). The two policies therefore share the
`ClarificationRequest`/`ClarificationAnswer` wire contract but differ only in *who
answers*.

### 3.3 The `_classify` ↔ forced-defer contract

`_classify` in `auto.py` and the glitch guards in `implementation.py` are coupled
through **rationale prefixes**. This is the one tight-coupling point in the design:

| Producer (`implementation.py`) | Consumer (`auto.py._classify`) | DeferKind |
|--------------------------------|--------------------------------|-----------|
| `rationale="structured_output_failed: ..."` | matches `_RATIONALE_STRUCT_FAIL` | `structured_output_failed` |
| `rationale="answer_was_question"` | matches `_RATIONALE_ANSWER_WAS_Q` | `answer_was_question` |
| `defer=True` (model's own defer) | plain | `explicit` |
| `confidence < min_confidence` | threshold | `low_confidence` |
| — | none of the above | `None` (accept) |

The prefix constants (`_FORCED_DEFER_*` in `implementation.py` ↔
`_RATIONALE_*` in `auto.py`) **must stay in sync**. This is the primary maintenance
hazard: a rename on one side silently breaks classification.

---

## 4. Design patterns

### 4.1 Schema-at-boundary (RFC-623)

Instead of post-hoc Python validation, `build_veritas_response_schema(n)` pushes the
"exactly N non-empty answers OR defer" constraint into the JSON schema given to the
structured-output call. The model is *structurally unable* to return a half-answer.
Post-call `coerce_veritas_response` only handles the answers-only shorthand — a
convenience, not a correctness path.

**Why it matters**: eliminates an entire class of "model returned 2 of 3 answers"
bugs at the LLM boundary rather than in fragile Python guards. Aligns with
RFC-630 (no keyword/regex heuristics) — the judgment is structural, not textual.

### 4.2 Glitch guards as forced defer

Two specific failure modes are converted to a **typed** defer rather than propagated
as exceptions:
- `StructuredOutputError` → `structured_output_failed` (the model couldn't satisfy
  the schema).
- Answer ending in `?` → `answer_was_question` (the model echoed a question instead
  of answering).

Both produce a `VeritasAnswerSchema` with `defer=True` and a prefixed `rationale`,
so the consumer never sees a bare exception. This makes Veritas **total**: every
code path yields either a valid answer or a typed defer.

### 4.3 Direct-function dispatch (not `task` tool)

Because Veritas is never model-dispatched, there is no prompt-injection surface
where the CoreAgent could be tricked into "calling Veritas" with attacker-chosen
arguments. The `ClarificationRequest` is built by `ClarificationDetector` from
loop state, not from model text. This is a deliberate security boundary.

### 4.4 Policy injection + interactive fallback

`AutoClarificationPolicy` takes `veritas_answer` as an injected callable and an
optional `interactive_fallback`. This gives:
- **Testability** — tests inject a stub `veritas_answer` to exercise `_classify`
  without LLM calls.
- **Graceful degradation** — RFC-623's escape hatch: a structured-output failure in
  an interactive run falls back to the human instead of killing the job. Autopilot
  (no human) keeps the hard-defer path, surfacing `awaiting_clarification`.

### 4.5 Project-instructions grounding

`build_veritas_user_prompt` inlines the workspace's `AGENTS.md`/`CLAUDE.md` (≤25k
chars) via the same `load_agent_instructions` loader the host CoreAgent uses. This
ensures Veritas's answers respect target-repo rules (e.g. package-boundary DAG,
terminology bans) without a second config path. Single source of truth for project
context.

### 4.6 Observability via parent-graph tracing

`_build_traced_invoke_config` attaches a Langfuse `RunnableConfig` that parents the
Veritas span under the StrangeLoop graph's trace, not as an orphan call. Token
costs and latency are attributable to the originating loop iteration.

---

## 5. Maintenance notes (hazards)

1. **Rationale-prefix coupling** (§3.3) — the only tight contract between
   `implementation.py` and `auto.py`. Any rename must be two-sided. A constant
   module or shared enum would reduce risk.
2. **`force_manual_origins` set** — high-stakes origins (execute, delegate, …) skip
   Veritas entirely. Adding a new origin requires deciding whether it belongs here.
3. **`min_confidence` threshold (0.4)** — currently a magic number in code. Per
   RFC-630, this belongs in `agent.loop.rules` or a config field; verify before
   adjusting.
4. **25k char cap on project instructions** — silent truncation. If a workspace's
   `AGENTS.md` exceeds this, Veritas sees a truncated ruleset. Not a bug, but worth
   noting for large monorepos.
5. **Rail kill-switch** — `agent.autopilot.rail_pause_auto_clarify=false` disables
   IG-737 behavior globally; `rail_pause` then always suspends. Fail-open-by-default
   is intentional.

---

## 6. DAG placement confirmation

| Concern | Package | Verified |
|---------|---------|----------|
| Veritas subagent (`answer`, prompts, schemas) | `soothe` | ✓ owned |
| `AutoClarificationPolicy`, selector, detector, origins | `soothe` | ✓ owned |
| `invoke_structured_chat`, `await_with_llm_call_policy` | `soothe_nano` (PyPI) | ✓ imported, not duplicated |
| Langfuse tracing helper | `soothe_sdk` (PyPI) | ✓ imported |
| `ClarificationRequest/Answer` wire types | `soothe` (sloop/clarification/protocol) | ✓ owned |

No reverse arrows into `soothe_daemon` or `soothe_cli`. Veritas is reachable from
the host only through `AutoClarificationPolicy`, which is constructed by
`selector.build_default_clarification_policy` at agent build time.
