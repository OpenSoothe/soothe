# Draft: Two-Pass Intake Classification

**Status**: Draft
**Created**: 2026-07-06
**Authors**: (discussion draft)
**Related**: RFC-630, IG-540, IG-518, IG-551
**Supersedes**: `docs/drafts/2026-07-06-one-pass-intent-classify-optimization.md` (one-pass approach rejected)
**Motivating incident**: Loop `019f369e-…-e47d` — actionable follow-up classified as `chitchat` and routed to fast-path END

---

## 1. Summary

This draft proposes a **two-pass intake architecture** replacing RFC-630's single LLM intake call. Pass 1 cleanly separates social vs task interactions; Pass 2 classifies work scope. This architectural separation resolves the systemic blind spot where acknowledgment+pivot phrasing ("Ok, now apply the fix") misroutes to `chitchat` fast-path.

---

## 2. Problem Statement

### 2.1 Root cause: Semantic overlap in single-label taxonomy

RFC-630's `chitchat` label conflates **interaction type** (social) with **scope** (no deliverable):

```
chitchat = "greeting/thanks/casual small talk" + "no work"
```

This creates an overlap zone where social prefix + work content collides:

| User GOAL | Model perception | Correct meaning |
|-----------|------------------|-----------------|
| `Ok, now apply the signature change` | "Ok" → social signal → `chitchat` | Acknowledgment pivot → work request |

**This is a systemic blind spot**, not a rare edge case. Any phrasing with:
- Social acknowledgment prefix ("Ok", "Got it", "Alright", "Sure")
- Pivot phrase ("now", "so", "about", "next", "then")
- Terse engineering reference

...falls into the same trap. Prompt patches whittle at the branch; architectural separation removes the root.

### 2.2 Context dominance amplifies the blind spot

IG-540's prior-goal projection biases the model toward "wrap-up" tone on continuation loops. When the user says "Ok, about the signature change" after a completed goal, the model sees:
- Prior context: "goal completed successfully"
- GOAL: "Ok, about..."

The "Ok" + prior completion reinforces "user is confirming/wrap-up" perception, suppressing the pivot signal.

### 2.3 Constraints for this draft

| In scope | Out of scope |
|----------|--------------|
| Two-pass architecture design | Fine-tuning pipeline (future) |
| Pass 1 and Pass 2 prompts | Checkpoint/goal_history fixes (separate IG) |
| Schema, routing, retry policy | Wire protocol changes |
| Eval harness | Regex/keyword guardrails on query text |

---

## 3. Proposed Architecture

### 3.1 Overview

```
User GOAL arrives
  ↓
Stage 1 (parallel): Pass 1 LLM ∥ checkpoint.load ∥ git_status
  ↓
Pass 1 output: {is_task: bool, confidence, social_response?, reasoning}
  ↓
If is_task == false → END (social fast-path, emit social_response)
If is_task == true → Pass 2
  ↓
Pass 2: prior projection + GOAL → scope classification
  ↓
Pass 2 output: {scope: trivial|simple|complex, goal_description, reasoning}
  ↓
Routing layer:
  if loop_state.new_goal_created and intake_label == "chitchat":
      force complex, log warning  # P0 hard constraint
  else:
      route by scope
  ↓
Branch dispatch: trivial | simple | complex paths
```

### 3.2 Pass 1: Social vs Task

**Purpose:** Clean binary decision — is this a social interaction or a work request?

**Prompt (compact, ~120 tokens):**

```xml
<INTAKE_PASS1>
Classify: social interaction or work request?

SOCIAL: greeting, thanks, identity question, small talk, standalone acknowledgment ("ok", "sure" alone).
WORK: references code/files/APIs/tests; requests action; acknowledgment + pivot ("ok, now...", "about the X...", "next: Y").

Rules:
- Names technical entity → WORK
- Pivot phrase after acknowledgment → WORK
- Uncertain → WORK

JSON only:
{"is_task":bool,"confidence":"high"|"medium"|"low","social_response":"string|null","reasoning":"≤15 words"}

social_response required when is_task=false. Match user's language/tone. Identity: "I'm Soothe, created by Dr. Xiaming Chen."

Examples:
"hi" → is_task:false, social_response:"Hi! How can I help?"
"thanks!" → is_task:false, social_response:"You're welcome!"
"ok, now apply the fix" → is_task:true
"about the refactor — finish it" → is_task:true
"alright, so the tests..." → is_task:true
</INTAKE_PASS1>
```

**Key design choices:**
- No prior context projection — clean decision boundary, no bias
- Pivot phrases explicitly listed — targets the blind spot
- Technical entity as hard signal → WORK
- Fail-safe toward WORK — uncertain routes to task
- `social_response` included for fast-path END

**Output schema:**

```json
{
  "is_task": true,
  "confidence": "high",
  "social_response": null,
  "reasoning": "acknowledgment pivots to request"
}
```

**Retry policy:** No retry on `confidence=low`. Fail-safe immediately to Pass 2 (treat as task). Pass 2 will route appropriately regardless.

### 3.3 Pass 2: Scope Classification

**Purpose:** Classify work scope — trivial, simple, or complex.

**Prompt (~100 tokens):**

```xml
<INTAKE_PASS2>
Classify work scope: trivial, simple, or complex?

trivial: one obvious action, no planning (e.g., single file read, simple query, math).
simple: one focused deliverable, light planning (e.g., single function fix, add one test).
complex: multi-step, multi-file, architecture, migration, multi-phase.

Rules:
- Multiple files/components → complex
- Architecture/system change → complex
- Uncertain → complex

JSON only:
{"scope":"trivial"|"simple"|"complex","goal_description":"imperative summary","reasoning":"≤15 words"}

goal_description: normalize as action statement, match user's language, preserve code/paths/IDs.

Examples:
"list the files in src/" → scope:trivial
"fix the type error in auth.py" → scope:simple
"refactor SessionStore across all callers" → scope:complex
"add tests for the new API endpoint" → scope:simple
"migrate the auth system to OAuth2" → scope:complex
</INTAKE_PASS2>
```

**Context packaging:**

```
[System]     Pass 2 prompt (above)
[Context]    PRIOR_GOAL_SUMMARY (from IG-540 projection)
[Human]      CURRENT_GOAL: <verbatim user text>
             TASK: classify scope only
```

Prior projection is included for:
- Reference resolution ("apply it" → what is "it"?)
- Continuation depth affecting scope (follow-up to complex work often complex)

**Output schema:**

```json
{
  "scope": "simple",
  "goal_description": "Apply signature change to downstream callers",
  "reasoning": "multi-file change, affects API consumers"
}
```

### 3.4 Routing and Derived Fields

**Derived at routing layer:**

```python
intake_label = "chitchat" if not is_task else scope
has_deliverable = is_task and scope != "trivial"
```

**Routing guard (P0 hard constraint):**

```python
if loop_state.new_goal_created and intake_label == "chitchat":
    intake_label = "complex"  # structural override
    log.warning("chitchat blocked by new-goal constraint, forcing complex")
```

If daemon has created a new goal record, `chitchat` is structurally invalid — the admission decision already committed to agentic work.

### 3.5 Latency Impact

| Query type | Passes | Added latency |
|------------|--------|---------------|
| Social (greeting, thanks) | Pass 1 only | 0ms (same as today) |
| Task | Pass 1 + Pass 2 | ~100-200ms added |

Budget: relaxed (<300ms acceptable). Pass 1 ultra-lean (~50-80 tokens); Pass 2 similar to today's intake.

---

## 4. Comparison to One-Pass Approach

| Aspect | One-pass (rejected) | Two-pass (proposed) |
|--------|---------------------|---------------------|
| Semantic boundary | Fuzzy overlap in `chitchat` | Clean separation: social/task then scope |
| Prior context bias | Problematic, requires repackaging | Eliminated in Pass 1, retained for Pass 2 only |
| Prompt maintenance | Perpetual catch-up with new phrasings | Stable — pivot phrases are structural pattern |
| Latency on task | Baseline | +100-200ms |
| Failure mode | Prompt patches never reach 100% | Architectural fix removes root cause |

---

## 5. Branch Wiring

Routing after Pass 2:

```
init_or_resume --(route_by_intent)--> {
  END                      // chitchat (Pass 1 is_task=false)
  resolve_decision         // trivial (synth plan in scratch)
  plan_generate            // simple (lightweight)
  bounded_evidence_gather  // complex (full spine)
  plan_assess              // continuation overlay (RFC-226)
}
```

Same branch destinations as RFC-630. Only the intake mechanism changes.

---

## 6. Success Criteria

| Criterion | Target |
|-----------|--------|
| e47d GOAL repro | Passes Pass 1 → `is_task=true`, never `chitchat` |
| Greeting/thanks regression | 100% remain social on eval set |
| False social-path rate | Near-zero on acknowledgment+pivot patterns |
| Added latency on task | <200ms median |
| Pass 1 retry rate | <3% (fail-safe immediately on low confidence) |

---

## 7. Implementation Phases

### Phase A — Pass 1 infrastructure

1. Create `IntakePass1Classifier` with compact prompt
2. Integrate into pre-graph gather (parallel with checkpoint/git_status)
3. Implement routing guard (P0 hard constraint)
4. Unit tests for pivot patterns

### Phase B — Pass 2 integration

1. Streamline existing intake prompt to 3-label (remove `chitchat`)
2. Pass prior projection to Pass 2 only
3. Derive `intake_label` and `has_deliverable` at routing
4. Integration tests for branch routing

### Phase C — Eval harness

1. Golden-set from production logs (e47d + similar)
2. Metrics: false social-path rate, latency p50/p95
3. CI gate: zero regression on greetings, zero false social-path on pivot patterns

### Phase D — Migration

1. Feature flag: `two_pass_intake=true/false`
2. Rollout: flag on → monitor → flag permanent → remove one-pass code
3. Delete legacy intake prompt fragments

---

## 8. Open Questions

1. **Pass 2 prompt tuning** — Confirm scope definitions match planner expectations.
2. **Prior projection truncation** — Optimal summary length before Pass 2 quality degrades?
3. **Feature flag duration** — How long to run dual-mode before removing one-pass?

---

## 9. References

- RFC-630: Start-Phase LLM Intake and Branch Routing
- IG-540: Intent Classify Prompt Ledger Optimization
- `packages/soothe/src/soothe/foundation/sloop/intention/classifier.py`
- Rejected one-pass draft: `docs/drafts/2026-07-06-one-pass-intent-classify-optimization.md`