# IG-774: Loop-Scoped Tool-Approval Allowlist

**Created**: 2026-09-06
**Status**: Implemented (verify_finally.sh green)
**Related**: IG-760 (reentrant loop state), IG-762 (clarification resume)

## Problem

Observed on loop `01a07661-d0d0-7152-95f1-29d16b6dd8f5` (goal: "create a new
folder and a new file in it, then rm the folder"):

The agent emitted `rm -rf /tmp/test_folder ...` and the safety pipeline
escalated it to the human relay (`command.dangerous.rm_root`,
`rm\s+-rf\s+/`). The human clicked **Approve** three times for near-identical
command variants (`rm -rf …`, the `delete` tool fallback, `rm -r …`). Each
approval only unblocked the loop turn — the `rm` itself stayed policy-denied
(`output='Policy denied action run_command'`), so the agent retried with
variants, each re-triggering the deterministic safety rule and re-prompting.

### Root causes

- **RC1 — human approval does not override a safety denial.** The pipeline
  (`tool_approval_pipeline.py`) treats banned safety rules as deterministic
  escalations and `interrupt_rules.py` documents that "the safety layer …
  rejects if the interrupt is approved anyway." So the Approve click is a
  no-op on the command; only the turn resumes.
- **RC2 — no loop-scoped approval memory.** Grep of the clarification package
  for any session/loop-scoped allowlist returns nothing. The pipeline is
  rebuilt every turn (`strange_loop.py` `set_clarification_mode` rebuilds via
  `build_clarification_policy_for_runner`), so even an in-process cache would
  be lost across the approval → next-tool-call gap.
- **RC3 — denied tool calls record `success=True`.** The Ledger records a
  policy-denied `rm` as a successful step (output is the denial string), a
  weak stop-signal that does not tell the agent to abandon the approach.

## Fix

### Scope

Owned `soothe` package only. The actual `rm_r` / `rm_root` safety patterns
live in `soothe_nano` (PyPI, not modified here) — out of repo scope. The
allowlist + override mechanism mitigates them without a nano release.

### 1. Pipeline allowlist mechanism (`tool_approval_pipeline.py`)

- `signature_for(tool, args) -> str | None`: stable per-action signature
  (the `command` string for `run_command`; the `file_path` for
  `edit_file`/`write_file`/`delete`; `None` for unknown tools). Structural
  field extraction only — no command-content heuristics (Rule 9).
- `approval_record(tool, args) -> dict | None`: `{"tool", "signature"}`.
- `evaluate(..., allowlist=)`: insert a new stage between deny rules and
  safety checks. An action whose `(tool, signature)` matches an allowlist
  record is approved (`stage="allowlist"`) and its safety check is skipped.
  Ordering: `deny_rule` (absolute reject — sudo etc.) → `allowlist`
  (human pre-approved this loop) → `safety_check` (escalate) →
  `default_approve`. Deny rules remain un-overridable.

### 2. Persisted graph channel (`stations.py`)

New `LoopGraphState` channel `tool_approval_allowlist: list[dict] | None`.
Persisted by the LangGraph checkpointer, so it survives worker crashes and
the per-turn policy rebuild (Rule 15 — state in storage, not in process).

### 3. Read-only projection (`protocol.py`, `execute.py`)

`LoopStateView` gains `tool_approval_allowlist: tuple[Mapping, ...] = ()`.
It is **not** serialized into `pending_clarification` (it is separate graph
state); `_build_loop_state_view` populates it from `state_dict`. The
freshly-built view (each turn) carries the current allowlist; the
deserialized view (from a parked request) leaves it empty, which is safe
because the pipeline only evaluates against the fresh view.

### 4. Wire to the policy (`auto.py`, `interactive.py`)

`evaluate(allowlist=tuple(request.loop_state.tool_approval_allowlist))` in
both `_answer_tool_approval` (auto) and the manual pre-filter. A matched
allowlist returns `approve`/`allowlist`, so the approved call actually runs
(the override) and identical retries do not re-escalate.

### 5. Record approvals (`stations/execute/execute.py`)

In `node_execute` at answer-consumption: when a human answer to a
`tool_approval` request is `approve`, append an `approval_record` per
action_request to `tool_approval_allowlist`. The locally-built list is
threaded into `_build_loop_state_view` so the next capture in the same turn
already reflects the approval, and returned in the node's state update for
persistence. Only written when dirty (non-dirty paths leave the channel
untouched, so a turn that captures a new interrupt does not wipe prior
approvals).

### What this fixes

- **RC1+RC2 together**: a human approval records the signature; the agent's
  retry of the same action matches the allowlist and runs, so the agent
  does not need to emit variants. The doom-loop is broken at the source.
- Exact-signature matching (no content normalization) is Rule 9-compliant.
  Variant retries (`rm -rf` → `rm -r`) are not auto-matched, but with the
  override fix the first approved command runs, so variants are not emitted.

## Out of scope / follow-up

- **RC3** (`success=True` on policy-denied): deferred. Changing step-result
  semantics is cross-cutting and risky; the allowlist+override removes the
  retry pressure that made RC3 visible. Tracked as a follow-up.
- **Narrowing nano's `rm_r` rule**: requires a `soothe-nano` release (PyPI).
  Not actionable in this repo.
- **Loop cap on allowlist size**: bounded by loop lifetime; no unbounded
  growth across loops (per-thread channel, discarded with the thread).

## Tests

- Pipeline: allowlist match → `approve`/`allowlist`; deny rule still rejects
  even when allowlisted; no-match → still escalates; unknown tool not
  matchable; `signature_for` field extraction.
- `node_execute`: human approve of a tool_approval records the signature and
  threads it to the next view (where fixture cost permits).

## Verification

`./scripts/verify_finally.sh` — zero lint, all tests green, module boundary
check passes.
