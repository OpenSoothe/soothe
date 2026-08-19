# Veritas vs Planner Subagent — Architecture Comparison & RFC/Impl Consistency

> Scope: the **Veritas** auto-clarification answerer and the **Planner** intake-only
> solution-report subagent — their architectural differences, and the consistency
> status of the RFCs / IGs / wiki that describe them.
>
> Related:
> - `docs/analysis/veritas-subagent-architecture.md` — Veritas deep dive
> - RFC-622 / RFC-623 / RFC-633 / RFC-304 / RFC-904
> - IG-752 / IG-753 (plan-spine removal), IG-737 (rail-pause veritas)

---

## 1. Two subagents, two architectural classes

Both live under `subagents/` but they are **not the same kind of thing**. The
distinction is the single most important takeaway of this analysis.

| Dimension | **Veritas** | **Planner** |
|-----------|-------------|-------------|
| Owned package | `soothe` (monorepo) | `soothe_nano` (PyPI) |
| Code location | `packages/soothe/src/soothe/subagents/veritas/` | `.venv/.../soothe_nano/subagents/plan/engine.py` |
| Dispatch mechanism | **Direct Python call** — `await veritas.answer(request)` | **Intake-only wire subagent** — `invoke_wired_subagent("planner")` |
| Reachable via `task` tool? | **No** — no `subagent_type`, no `SubAgentMiddleware` registration | **No** — intake-only allowlist (`INTAKE_ONLY_WIRE_SUBAGENTS`) hides it from `task` |
| LangGraph node? | No — a typed async function | Yes — a `CompiledSubAgent` `StateGraph` (recon → proposal → emit) |
| Output contract | `VeritasAnswerSchema` (Pydantic + per-request `oneOf` JSON Schema) | `PlanRefinement` structured output → final `AIMessage` (solution report markdown) |
| Consumer | `AutoClarificationPolicy` (sole consumer) | `delegate.py::invoke_wired_subagent` → host writes `.soothe/plans/*.md` → RFC-622 review |
| LLM call shape | Single structured-output call (`invoke_structured_chat`) | Multi-round LangGraph: `bind_tools` recon loops + proposal-design loops |
| Tools available | None (prompt-only) | Readonly filesystem tools: `glob`, `grep`, `ls`, `read_file`, `file_info` |
| Human gate | None — it *replaces* the human | RFC-622 clarification: Approve / Reject / More comments |
| Traceability | Langfuse span under parent loop (`subagent.veritas`) | Orphan SubAgent card + `soothe.subagent.planner.progress` events |

### 1.1 Why the asymmetry is correct

Veritas is an **answerer**, not an investigator. It stands in for a human who
was asked a yes/no or pick-one question; giving it tools would be a category
error. Its entire job is one structured-output LLM call grounded in the
`LoopStateView` (original request, goal, plan summary, project instructions).

Planner is an **investigator + author**. It must read the repo before it can
prescribe concrete edits, so it gets readonly tools and a multi-round graph.
Its deliverable is a markdown artifact, not a JSON answer.

The dispatch asymmetry follows from this: Veritas is called synchronously
inside a policy that the loop already controls; Planner is a long-running
specialist streamed through the orphan-card wire surface.

---

## 2. Veritas architecture (summary)

**Surface**: `veritas.answer(request: ClarificationRequest) -> VeritasAnswerSchema`

```
ClarificationRequest (from StrangeLoop node)
        │
        ▼
build_veritas_system_prompt()          # static rules; "never ask a question back"
build_veritas_user_prompt(loop_state)  # request, goal, intent, plan, workspace,
                                       #   AGENTS.md/CLAUDE.md (≤25k), skills, steps
build_veritas_response_schema(n)       # oneOf: exactly N answers OR defer
        │
        ▼
invoke_structured_chat(...)            # soothe_nano shared helper
   wrapped in await_with_llm_call_policy(...)   # rate-limit handling
   wrapped in Langfuse RunnableConfig           # traced span
        │
        ▼
coerce_veritas_response(data, n)       # fill metadata on answers-only responses
VeritasAnswerSchema.model_validate(data)
        │
        ▼
Glitch guards (RFC-623):
  • StructuredOutputError  → forced defer "structured_output_failed: ..."
  • answer ends with "?"   → forced defer "answer_was_question"
        │
        ▼
AutoClarificationPolicy._classify(result) → DeferKind | None
  explicit | low_confidence | structured_output_failed | answer_was_question | None
        │
        ▼
  None  → ClarificationAnswer(source="veritas")
  kind  → ClarificationDeferredError (terminal) OR interactive fallback (RFC-623)
```

**Key invariant**: the `oneOf` JSON Schema makes "exactly N non-empty answers
OR defer" structurally enforced at the LLM boundary, not by a post-hoc Python
guard. This is the RFC-623 fix for the empty-answer false-defer regression.

---

## 3. Planner architecture (summary)

**Surface**: `create_plan_subagent(model, config, context) -> CompiledSubAgent spec`

```
invoke_wired_subagent("planner")        # from slash /preferred_subagent
        │
        ▼
build_plan_engine(model, plan_opts, ...)
  StateGraph(PlanSubagentState)
    ├─ recon node: model.bind_tools(readonly_tools) → ToolNode
    │    (max_recon_rounds; evidence is internal, not the deliverable)
    ├─ proposal node: invoke_structured_chat_typed(PlanRefinement)
    │    (max_plan_rounds; plan_markdown + rationale + finish_planning)
    └─ emit_final: AIMessage(solution report)
        │
        ▼
host (delegate.py):
  write .soothe/plans/{UTC}-{slug}.md
  pending_clarification (origin=planner_subagent_review)
  → await_clarification (RFC-622 interrupt)
        │
        ▼
TUI: plan body + Approve / Reject / More comments
  Approve  → DISPATCH (root grounded with approved plan; NOT plan_generate)
  Reject   → goal_completion (rejected)
  Comments → re-invoke planner with prior plan + comments
```

**Key invariant (RFC-633 / RFC-904)**: Approve **must not** enter
`plan_generate`. The approved markdown grounds the DISPATCH root THREAD;
CE StepDAG children come from `decompose_task`. The legacy LLMPlanner /
PlanPhase host spine was deleted by IG-752/IG-753.

---

## 4. Where they meet

The two subagents share exactly one integration point: the **RFC-622
clarification relay**.

- **Planner** is a *producer* of clarification requests — its review gate
  uses `origin=planner_subagent_review`.
- **Veritas** is a *consumer* of clarification requests — `AutoClarificationPolicy`
  answers them.

But Veritas does **not** answer planner review clarifications. The planner
review origin is in `force_manual_origins` (it requires a real human
Approve/Reject), so `AutoClarificationPolicy.requires_manual()` short-circuits
to the interactive relay before Veritas is ever called. This is deliberate:
auto-approving a plan would defeat the purpose of the review gate.

The other shared surface is **IG-737** (rail `pause_for_user`), where Veritas
*does* answer rail-pause clarifications in autopilot (origin `rail_pause`, not
in `force_manual_origins`). Planner is not involved there.

---

## 5. RFC / IG / Wiki consistency analysis

### 5.1 Veritas — consistent ✅

| Artifact | Status | Notes |
|---------|--------|-------|
| RFC-622 (Clarification Relay) | Draft | Accurately describes the relay, `await_clarification` node, Veritas as auto-answerer. |
| RFC-623 (Veritas Robustness) | Draft | Accurately describes `invoke_structured_chat` migration, `oneOf` schema, `DeferKind`, interactive fallback. |
| IG-737 (Rail-pause Veritas) | Done | `rail_pause` origin, PROCEED/PAUSE vocabulary, autopilot auto-clarify. Matches code. |
| `docs/analysis/veritas-subagent-architecture.md` | Current | Matches implementation. |
| `docs/wiki/subagents.md` | Current | Lists Veritas as "(auto-invoked)". Accurate. |
| Code (`subagents/veritas/`) | — | Matches all three RFCs. |

Veritas has no consistency drift. The RFCs are still "Draft" (not "Implemented")
but their content matches the code; this is a status-label lag, not a design
discrepancy.

### 5.2 Planner — **multiple inconsistencies** ⚠️

| Artifact | Claim | Reality | Severity |
|---------|-------|---------|----------|
| `docs/wiki/protocols/planner.md` | "Status: Implemented" at `packages/soothe/src/soothe/protocols/planner.py` and `loop_planner.py` | **Files do not exist.** `protocols/` contains only `loop_working_memory.py`, `runner.py`, `__init__.py`. `PlannerProtocol` now lives in `soothe_sdk.protocols.planner`. | **High** — wiki points to deleted paths |
| `docs/wiki/protocols/planner.md` | Describes `LoopPlannerProtocol` two-phase (assess→generate) as live | `LLMPlanner`/`PlanPhase` deleted by IG-752/IG-753; `resolve_planner()` always returns `None`. RFC-904 replaces the spine with DISPATCH/THREAD/RECONCILE/ROOT_EVAL. | **High** — wiki describes removed architecture |
| `docs/wiki/protocols/planner.md` | Continuation routing table (trivial/simple/complex → plan_assess/plan_generate) | RFC-904 §Supersedes explicitly removes pass2 and complexity-tiered plan routes. | **High** — wiki table is obsolete |
| RFC-304 (PlannerProtocol) | "Status: Draft", "Implementation: IG-372 (LLMPlanner two-phase), IG-329" | IG-372/IG-329 are not in `docs/impl/` (likely archived or never existed as tracked IGs). LLMPlanner is deleted. The `PlannerProtocol` *interface* (in sdk) survives but has no host implementation. | **Medium** — RFC header references stale IGs |
| RFC-633 (Planner Plan Artifact) | "Status: Draft" | Implementation matches (readonly recon, `.soothe/plans/`, Approve/Reject). But §4.1 says "Approve → DISPATCH (not plan_generate)" which is a RFC-904 patch — the original RFC-633 predated RFC-904. | **Low** — patched inline, mostly accurate |
| RFC-904 (Recursive Decomposition) | "Status: Proposed" | IG-752/IG-753 already executed the deletion half. The DISPATCH/THREAD/RECONCILE topology is partially landed (resolve_planner→None, plan-spine gone) but the full recursive `decompose_task` + CE reconcile is not yet implemented. | **Medium** — RFC status lags partial impl |
| `docs/wiki/subagents.md` | "Core Soothe ships five built-in subagents: planner, deep_research, academic_research, browser_use, veritas" | Accurate — all five exist. But the planner description ("Plan-mode routing") is thin and doesn't mention it's intake-only or the review gate. | **Low** — incomplete, not wrong |
| IG-753 (Delete LLMPlanner) | "Status: Done" | Accurate — `resolve_planner` returns `None`, plan-spine deleted. | ✅ |
| Code (`runner/resolver/__init__.py`) | `resolve_planner` docstring: "always None after plan-spine removal" | Accurate. | ✅ |

### 5.3 Root cause of the planner drift

The drift is a **documentation-lag artifact of IG-752/IG-753** (plan-spine
deletion) landing **before** RFC-904 (the replacement) reached Accepted/Implemented
status. The wiki and RFC-304 still describe the pre-deletion world
(`PlannerProtocol` host impl, `LoopPlannerProtocol` two-phase, pass2 routing)
while the code has already moved to the post-deletion world
(`resolve_planner→None`, intake-only wire subagent, DISPATCH cutover).

This is the classic "RFC status label hasn't caught up" pattern: the deletion
IGs are Done, but the RFCs they invalidate are still Draft, and the wiki page
that transcribed those RFCs still says "Implemented".

---

## 6. Recommended remediation (decomposed as follow-up subtasks)

The consistency gaps split into three independent workstreams:

1. **Wiki `protocols/planner.md` rewrite** — the highest-severity item. The page
   points to deleted files and describes removed architecture. Needs a full
   rewrite to reflect: `PlannerProtocol` lives in `soothe_sdk.protocols.planner`
   (interface only, no host impl); `LoopPlannerProtocol` two-phase is deleted;
   the live "planner" is the intake-only nano wire subagent (RFC-633); the
   StrangeLoop spine is RFC-904 recursive decomposition (Proposed, partial).

2. **RFC-304 status + IG-reference correction** — update the RFC header to
   reflect that the host `PlannerProtocol` implementation was removed by
   IG-752/IG-753, the interface survives in `soothe_sdk`, and the IG-372/IG-329
   references are stale. Optionally retitle to "PlannerProtocol Interface
   (interface-only)".

3. **RFC-904 status reconciliation** — RFC-904 is "Proposed" but the deletion
   half is already landed. Either (a) split into "Accepted (deletion)" +
   "Proposed (recursive decomposition topology)" or (b) annotate the RFC body
   with a "Partial implementation" note pointing at IG-752/IG-753 as the
   landed portion.

4. **RFC-622 / RFC-623 status-label bump** — both are "Draft" but fully
   implemented. Low priority (content is accurate), but the status labels
   mislead readers about maturity.

These are documentation-only changes; no code changes are required.
