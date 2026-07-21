# IG-701: Event Naming & Package-Boundary Fixes (Part 2)

**Guide**: IG-701
**Created**: 2026-07-21
**Related**: IG-678 (Nano Host-Coupling Excision, Part 1 — boundary script guards),
`AGENTS.md` §3b/§3c/§7b, `scripts/check_nano_duplicate_symbols.py`,
`scripts/check_nano_docstring_refs.py`, `scripts/verify_finally.sh`,
event-registry-collapse memory (`soothe_sdk.core.registry` canonical owner)
**Status**: COMPLETE — PR-1/PR-2/PR-3/PR-4 all DONE; `verify_finally.sh` fully green (all 6 packages: tests + lint + format + vulture + boundary checks). C-series wire renames deferred to a follow-up RFC (see "Out of scope").

---

## Progress

### PR-4 — Dead veritas events removed (DONE, 2026-07-21)
- Deleted `packages/soothe/src/soothe/subagents/veritas/events.py` (the 3 event
  classes `VeritasRequestedEvent`/`VeritasAnsweredEvent`/`VeritasDeferredEvent`,
  the 3 `SUBAGENT_VERITAS_*` constants, and the 3 `register_event` calls).
  These had **zero construction sites** in non-test code — the live
  clarification relay uses `ClarificationRequestedEvent`/`ClarificationAnsweredEvent`/
  `ClarificationDeferredEvent` (host `foundation/sloop/clarification/events.py`,
  emitted at `runner/_runner_strange_loop.py:683-711`) under the
  `soothe.loop.clarification.*` wire namespace.
- Cleaned `veritas/__init__.py`: removed the 6 dead re-exports + the
  `from soothe.subagents.veritas import events as _veritas_events` side-effect
  import. `VeritasAnswerSchema`, `build_veritas_response_schema`, `answer`
  remain (live, schema + implementation).
- Removed `_importlib.import_module("soothe.subagents.veritas.events")` from
  host `foundation/events/catalog.py`; ruff then removed the now-unused
  `import importlib as _importlib` line.
- **Kept**: SDK ux classifier tests (`test_subagent_progress.py`,
  `test_subagent_wire_display.py`) that reference the string literal
  `"soothe.subagent.veritas.requested"` — they test the classifier's string
  handling, independent of the model.
- **Verification**: `verify_finally.sh` fully green. `import soothe.subagents.veritas` succeeds; `ClarificationRequestedEvent` (live relay) intact.

### PR-3 — Daemon events constants module (DONE, 2026-07-21)
- Created `packages/soothe-daemon/src/soothe_daemon/events/constants.py` (plural,
  matching host `foundation/events/` convention; distinct from the existing
  `soothe_daemon/event/` singular dir which holds bus/topic/reattachment
  infrastructure). Centralizes the 12 daemon-owned wire constants:
  `CHANNEL_MESSAGE_RECEIVED`, `OUTPUT_TEXT_COMPLETE`/`DELTA`/`END`,
  `OUTPUT_UI_RENDER`, `OUTPUT_PROGRESS`, `OUTPUT_REASONING`,
  `SKILLIFY_RETRIEVE_COMPLETED`/`INDEX_STARTED`/`UPDATED`/`UNCHANGED`/`FAILED`.
- `events/__init__.py` re-exports the constants for a single import surface.
- Repointed `channels/events.py` (7 type fields), `skillify/events.py` (5
  constants), and `channels/websocket.py` (2 inline `"soothe.output.text.*"`
  literals) to import from the new module.
- **No rename**: the snake-glue skillify names (`retrieve_completed`,
  `index_started`, etc.) are kept as-is — renaming is C-series, deferred.
- **Verification**: `verify_finally.sh` fully green; all daemon channel + skillify events resolve via the new constants module (verified by instantiation).

### PR-1 — 6 models → nano sole ownership + custom_event/StreamChunk consolidation (DONE, 2026-07-21)
- Deleted the 6 dead-duplicate event model classes from host
  `soothe/foundation/events/catalog.py` (`StreamEndEvent`, `LLMRetryAttemptEvent`,
  `MemoryRecalledEvent`, `MemoryStoredEvent`, `PolicyCheckedEvent`,
  `PolicyDeniedEvent`). Host now imports them from
  `soothe_nano.events.catalog` — single canonical class, no more
  last-importer-wins registry clobber.
- `LLMRetryAttemptEvent` was **completely unreferenced** in host/daemon non-test
  code — ruff correctly dropped it from the import (it's owned + registered
  only by nano). The other 5 are re-exported through host catalog's existing
  `_reg()` calls (templates/priority match nano's exactly, so idempotent).
- `StreamChunk` consolidation: removed host-internal duplicates in
  `soothe/protocols/runner.py` and `soothe/runner/_runner_shared.py`; both now
  `from soothe.foundation.events import StreamChunk`. Canonical definition
  remains in host `foundation/events/catalog.py`. nano keeps its own copy
  (nano cannot import host; its copy is in `__all__` but never called by nano).
- `custom_event()` canonical definition stays in host `foundation.events.catalog`
  (only real callers are host docstrings; runner subsystem uses private `_custom`).
- **Verification**: `verify_finally.sh` **fully green** — all 6 packages' tests
  (sdk/nano/client-python/cli/soothe/daemon), lint, format, vulture, boundary
  checks pass. Identity check: all 6 models + `StreamChunk` resolve to single
  canonical objects across packages; `REGISTRY.get_meta()` returns nano classes
  for `soothe.internal.policy.checked`, `.memory.recalled`, `soothe.stream.end`,
  `soothe.cognition.llm.retry.attempt`.
- **Environment note**: the earlier 700-failure run was an environment issue
  (editable installs of `soothe`/`soothe-cli`/`soothe-daemon` missing from the
  venv), resolved by `uv sync --all-packages --all-extras`. Not a code problem.

### PR-2 — Constants canonicalization (DONE, 2026-07-21)
- Added 6 protocol-primitive constants (`ERROR`, `LLM_RETRY_ATTEMPT`,
  `MEMORY_RECALLED`, `MEMORY_STORED`, `POLICY_CHECKED`, `POLICY_DENIED`) to
  `soothe_sdk/core/events.py` as canonical home; `STREAM_END` already existed.
  Added all 7 to SDK `core/__init__.py` re-export + `__all__`.
- `soothe_nano/events/constants.py`: replaced 7 literal assignments with
  `from soothe_sdk.core.events import (...)` re-export; fixed docstring that
  wrongly pointed at host `soothe.foundation.events.constants` (§7b rule 3:
  no host module paths in nano).
- `soothe/foundation/events/constants.py`: re-export the 7 from SDK at top of
  file; deleted duplicate literal defs (MEMORY_*, POLICY_*, ERROR, STREAM_END,
  LLM_RETRY_ATTEMPT); deleted dead self-assignment no-op block
  (`STRANGE_LOOP_STEP_STARTED = STRANGE_LOOP_STARTED` etc.).
- **Verification**: identity check passes (all 7 constants are the same
  object across SDK/nano/host — re-export, not redefinition).
  `check_nano_duplicate_symbols.py` ✓, `check_nano_docstring_refs.py` ✓,
  `check_module_import_boundaries.sh` ✓, ruff format/lint ✓ (auto-fixed import
  sort in `core/__init__.py`).
- **Test baseline confirmed**: SDK `7 failed, 348 passed` and nano
  `~223 failed, 1216 passed` are **identical with and without** PR-2 changes
  (verified by stashing submodule changes and re-running with verify_finally's
  exact `-n4 --dist=loadgroup` flags). The pre-existing failures are the
  documented `verify_finally` blocker (RFC-630 context-engine/LoopCardLedger
  breakage), not introduced by this work. Zero regressions.

---

## Context

The event-registry machinery (`EventPriority` / `EventMeta` / `EventRegistry` /
`REGISTRY` / `register_event`) was collapsed into `soothe_sdk.core.registry` so
nano, host, and daemon share one authoritative event-type index. But that
collapse stopped at the **registry singleton**: the event **model classes**
and the type-string **constants** are still independently declared per package.
That half-finished collapse is where the leaks and naming drift live.

A naming audit across `soothe-sdk`, `soothe-nano`, `soothe` (host), and
`soothe-daemon` surfaced five issue families, A–E. Two are **boundary
correctness bugs** (silent registry clobber, duplicated constants); three are
**naming-convention drift** (segment-count and action-grammar inconsistency).
This IG fixes the boundary bugs (A, B, D) and the daemon constants module
gap (B4). The wire renames (C1–C4) are **deferred to a follow-up RFC** —
see "Out of scope (C-series)".

### Verified facts driving the design

1. **Six protocol-primitive models are duplicated across nano ↔ host** with
   identical type strings: `StreamEndEvent`, `LLMRetryAttemptEvent`,
   `MemoryRecalledEvent`, `MemoryStoredEvent`, `PolicyCheckedEvent`,
   `PolicyDeniedEvent`. Host's copies are **dead duplicates**: a repo-wide
   grep finds them constructed **only** in their own `class` def + the `_reg()`
   registration call — never instantiated in host/daemon non-test code. Nano
   constructs `PolicyCheckedEvent`/`PolicyDeniedEvent`
   (`soothe_nano/middleware/policy.py:83,93`); the other four are registered
   primitives no package constructs directly. `EventRegistry.register()`
   (`soothe_sdk/core/registry.py:90`) is a blind overwrite — **last importer
   wins**, so `isinstance(event, nano.MemoryRecalledEvent)` silently breaks if
   the host class registered last.

2. **`custom_event()` / `StreamChunk` are defined in four places**: host
   `foundation/events/catalog.py:120,127`, host `runner/_runner_shared.py:8`,
   host `protocols/runner.py:12`, and nano `events/catalog.py:26,30`.

3. **The CLI is a client** — `packages/soothe-cli/pyproject.toml` depends on
   `soothe-sdk` + `soothe-client-python` only, **not** on the host `soothe`
   package. It imports 16 orchestration constants from `soothe_sdk.core.events`
   (`tui/textual_adapter.py:49`, `runtime/turn/prepare.py:13`,
   `runtime/headless/processor.py:13`). The daemon *does* depend on host.
   This means: **wire-visible constants consumed by the CLI must live in the
   SDK** (the protocol-contracts layer) — they cannot move to the host without
   forcing a CLI→host dependency (a layering violation; CLI sits above the
   daemon, not coupled to the agent core).

4. **SDK independence is enforced** (`verify_finally.sh:428`): the SDK must not
   import `soothe`/`soothe_nano`/`soothe_daemon`/`soothe_cli`. So the SDK
   cannot re-export constants *from* the host. The SDK is therefore the
   **canonical home for wire-visible string constants** that the CLI needs.

5. **Veritas events are dead**: `VeritasRequestedEvent` /
   `VeritasAnsweredEvent` / `VeritasDeferredEvent` (host
   `subagents/veritas/events.py`) are defined and registered but have **zero
   construction sites** in non-test code. The live clarification relay uses
   `ClarificationRequestedEvent` / `ClarificationAnsweredEvent` /
   `ClarificationDeferredEvent` (host `foundation/sloop/clarification/events.py`,
   emitted at `runner/_runner_strange_loop.py:683-711`) under the
   `soothe.loop.clarification.*` wire namespace (constants in
   `soothe_sdk.core.events`).

6. **`REPLAY_COMPLETE = "replay_complete"`** is the only constant without the
   `soothe.` prefix. It is an **intentional control-plane wire envelope**
   marker, documented in `foundation/events/visibility.py:84` alongside
   `status`/`error`/`loop_*_response`. Not a violation — leave it.

7. **The three client submodules** (`client/go`, `client/typescript`,
   `client/python`) hardcode C-series wire strings in source **and** tests
   (`soothe.stream.end`, `soothe.subagent.deep_research.*`,
   `soothe.system.autopilot.*`). `verify_finally.sh` runs **Python packages
   only** (`ALL_PACKAGES=(soothe-sdk soothe-nano soothe-client-python soothe-cli
   soothe soothe-daemon)`) — a Python-side wire rename would pass green while
   breaking the Go/TS clients silently.

8. **Daemon has no events constants module**: channel
   (`channels/events.py`) and skillify (`skillify/events.py`) declare type
   strings inline. Every other package centralizes.

### Guard compatibility (verified)

- `check_nano_duplicate_symbols.py` flags nano symbols the host also defines
  **with zero import references inside nano**. Re-exporting an SDK constant in
  nano via `from soothe_sdk.core.events import STREAM_END` adds an internal
  reference, so it will **not** trip this guard.
- `check_nano_docstring_refs.py` scans for `IG-NNN`/`RFC-NNNN` strings only,
  not imports. Compatible.
- `check_module_import_boundaries.sh` rule 3b bans nano importing
  `soothe`/`soothe_daemon`/`soothe_cli` — **not** `soothe_sdk`. nano→sdk is
  the allowed direction and is already in use.

---

## Goal

Single-ownership event models and constants that respect package boundaries,
with zero wire-format change. Concretely:

- The 6 duplicated protocol-primitive models have **one owner** (nano).
- The duplicated string constants have **one owner** (SDK), re-exported by
  nano + host.
- `custom_event()` / `StreamChunk` have **one owner** (host `foundation.events`),
  nano re-exports from there — or, if the host can't be imported by nano, both
  import from the SDK. (See Workstream A2 for the resolution.)
- Daemon gets a constants module.
- Dead veritas events are removed.
- Wire-visible constants the CLI needs stay in the SDK (protocol-contracts
  layer) — B3 "full move to host" is rejected as infeasible (see Decision B3).

## Decisions (locked, from planning)

- **B3 shape: surgical split.** Wire-visible constants stay in the SDK (CLI/
  Go/TS/daemon import them there — correct for a protocol-contracts package).
  Only the 6 duplicated *models* move to single ownership (folded into B1/B2).
  SDK `__all__` stays as-is. Rationale: the CLI cannot depend on the host
  without a layering violation, and the SDK cannot re-export from the host
  (independence rule).
- **C-series: deferred.** All wire-string renames (3-seg → 4-seg,
  over-segmented → 4-seg, autopilot domain unification, action-grammar
  normalization) are **out of scope** and deferred to a follow-up RFC. The
  client submodules hardcode these strings and are outside `verify_finally`;
  a safe rename requires a dual-emit migration window (the "Alias + keep old"
  option chosen in planning *is* the deferral — aliasing the Python model
  classes/constants without touching wire strings is exactly Workstream A/B).
- **No wire-format change in this IG.** Every fix is source-internal: move
  model definitions, rebind imports, delete dead duplicates, add a module.

---

## Out of scope (C-series — deferred to a follow-up RFC)

These naming issues are real but require a wire migration with cross-submodule
client coordination. They are documented here as the RFC seed, **not** executed:

- **C1. 3-segment type strings** → 4 segments: `soothe.stream.end` →
  `soothe.stream.turn.end` (or similar); `soothe.stream.heartbeat` →
  `soothe.stream.heartbeat.beat`; `soothe.error.tool`/`.subagent` →
  `soothe.error.tool.failed`/`soothe.error.subagent.failed`;
  `soothe.output.progress`/`.reasoning` → `soothe.output.progress.update`/
  `soothe.output.reasoning.chunk`; `soothe.skillify.*` snake-glue →
  `soothe.skillify.retrieve.completed` / `soothe.skillify.index.started` etc.
- **C2. Over-segmented nano subagent events** → 4 segments:
  `soothe.subagent.academic_research.gather.summary` →
  `soothe.subagent.academic_research.gather_summary` (or fold `step.completed`
  to a 4-seg shape). Applies to academic_research + deep_research.
- **C3. Action-grammar normalization** per component: pick past-tense verb
  *or* `noun_verb` snake, apply uniformly. weaver (`dispatched` vs
  `analysis_started`), plan (`created`/`reflected` vs `creating`),
  mcp (`connected`/`reconnecting`/`connect_failed`), subagent lifecycle
  (`started`/`completed` vs `requested`/`answered` vs `dispatched`).
- **C4. Autopilot domain unification**: move `soothe.cognition.autopilot.
  mode_switched` into `soothe.system.autopilot.*`; normalize the chaotic
  `soothe.internal.autopilot.*` namespace (4 shapes: bare verb,
  `goal.<action>`, `pool_changed` snake, `progress.<x>` nested).

The follow-up RFC must define a dual-emit/alias window, update all three
client submodules, and add the client submodules to a cross-language
verification step (currently absent from `verify_finally.sh`).

---

## Workstream A — Single-ownership for the 6 duplicated protocol models

### A0. Ownership assignment (locked)

Owner: **nano** (`soothe_nano/events/catalog.py`). Rationale: nano constructs
the policy models; the other four are shared protocol primitives that nano
legitimately hosts; the SDK owns only the *string constants* (the CLI needs
them and can't import nano). Host's 6 copies are dead duplicates → **delete,
import from nano**.

Edge case: the host (`foundation/events/catalog.py`) currently defines these 6
and registers them via `_reg()`. After this workstream, host imports the nano
classes and either (a) keeps its `_reg()` calls referencing the imported class,
or (b) drops them (nano's catalog already registers at nano import time, and
host imports nano's mcp/plugin/skill modules at `catalog.py:936-943`). Choice:
**(a) keep host `_reg()` calls but pointing at the imported nano class** —
preserves host's summary-template/priority/verbosity overrides without
re-introducing a duplicate class.

### A1. PR-1 — Make nano the sole owner of the 6 models

Files:
- `packages/soothe-nano/src/soothe_nano/events/catalog.py` — **keep** the 6
  class definitions (no change to the classes themselves).
- `packages/soothe/src/soothe/foundation/events/catalog.py` — **delete** the
  6 class definitions (`StreamEndEvent` L272, `LLMRetryAttemptEvent` L400,
  `MemoryRecalledEvent` L437, `MemoryStoredEvent` L443, `PolicyCheckedEvent`
  L476, `PolicyDeniedEvent` L483). **Add** import:
  ```python
  from soothe_nano.events.catalog import (
      LLMRetryAttemptEvent,
      MemoryRecalledEvent,
      MemoryStoredEvent,
      PolicyCheckedEvent,
      PolicyDeniedEvent,
      StreamEndEvent,
  )
  ```
  Host already depends on `soothe-nano` (`pyproject.toml`); this import is
  boundary-legal (host→nano allowed). Keep the existing `_reg(...)` calls —
  they now reference the imported nano class, preserving host verbosity/
  summary/priority overrides.
- `packages/soothe/src/soothe/foundation/events/__init__.py` — the re-export
  `from .catalog import (… MemoryRecalledEvent …)` still resolves (now via the
  nano import re-exported through host catalog). No change needed unless the
  import list needs the 6 names added explicitly; verify `__all__` already
  lists them (it does — L208-211, etc.).

### A2. PR-1 (cont.) — Consolidate `custom_event()` / `StreamChunk`

Four definitions → one. Owner: **host `foundation/events/catalog.py`** (the
canonical event-infrastructure module; nano cannot import host). Resolution:
- `packages/soothe-nano/src/soothe_nano/events/catalog.py` — **delete** the
  local `StreamChunk` (L26) and `custom_event()` (L30). Nano consumers of
  `custom_event`? Grep `packages/soothe-nano/src` for `custom_event(` usage —
  if nano uses it, nano must own a copy (nano can't import host). **Verify
  before deleting**: if nano has internal callers, **keep nano's copy** and
  instead delete the host `runner/_runner_shared.py:8` and `protocols/runner.
  py:12` duplicates (host internal dupes), leaving host `foundation.events`
  + nano `events.catalog` as the two legitimate per-package copies (each
  package owns its own helper for its own consumers; the SDK is the third if
  it needs one). The 4→2 reduction removes the host-internal dupes.
- `packages/soothe/src/soothe/runner/_runner_shared.py:8` (`StreamChunk`) and
  `packages/soothe/src/soothe/protocols/runner.py:12` (`StreamChunk`) —
  **delete**; import from `soothe.foundation.events` (or
  `soothe.foundation.events.catalog`). These are host-internal duplicates of
  the host canonical definition.

**Pre-check before A2**: run
`grep -rn "custom_event(" packages/soothe-nano/src packages/soothe/src packages/soothe-daemon/src`
to enumerate every caller and confirm no behavior change from the consolidation.

### A3. Verification (PR-1)

- `./scripts/verify_finally.sh` green (lint, format, tests, vulture, deps).
- `python scripts/check_nano_duplicate_symbols.py` — must report 0 (the host
  copies are deleted, so no nano/host symbol collision).
- `python scripts/check_nano_docstring_refs.py` — green (no docstrings touched
  beyond plain-English).
- Spot-check: `python -c "from soothe.foundation.events import MemoryRecalledEvent, StreamEndEvent; print(MemoryRecalledEvent, StreamEndEvent)"` resolves to nano classes.
- Import-order check: `python -c "import soothe.foundation.events.catalog"` does
  not raise (no circular import introduced by host→nano catalog import — host
  already imports nano modules at the bottom of catalog.py).

---

## Workstream B — Single-ownership for string constants + daemon constants module

### B0. Ownership assignment (locked)

Owner for wire-visible constants: **SDK** (`soothe_sdk/core/events.py`).
Rationale: the CLI imports `STREAM_END` from the SDK and cannot import nano or
host. nano + host **re-export** (import + re-export) rather than redefine.

### B1. PR-2 — Canonicalize the 6 primitive constants in the SDK; re-export from nano + host

The SDK already defines `STREAM_END = "soothe.stream.end"` (L99). Add the
missing five to `soothe_sdk/core/events.py` if absent (verify first — some may
already exist):
```python
ERROR = "soothe.error.general.failed"
LLM_RETRY_ATTEMPT = "soothe.cognition.llm.retry.attempt"
MEMORY_RECALLED = "soothe.internal.memory.recalled"
MEMORY_STORED = "soothe.internal.memory.stored"
POLICY_CHECKED = "soothe.internal.policy.checked"
POLICY_DENIED = "soothe.internal.policy.denied"
```
(These are wire strings the SDK already references in `ux/types.py` and
docstrings — making them first-class SDK constants is consistent.)

Files:
- `packages/soothe-sdk/src/soothe_sdk/core/events.py` — add the 5 missing
  constants (if absent); add to `__all__`.
- `packages/soothe-nano/src/soothe_nano/events/constants.py` — **replace** the
  7 literal assignments (`ERROR`, `LLM_RETRY_ATTEMPT`, `MEMORY_RECALLED`,
  `MEMORY_STORED`, `POLICY_CHECKED`, `POLICY_DENIED`, `STREAM_END`) with
  re-exports:
  ```python
  from soothe_sdk.core.events import (
      ERROR,
      LLM_RETRY_ATTEMPT,
      MEMORY_RECALLED,
      MEMORY_STORED,
      POLICY_CHECKED,
      POLICY_DENIED,
      STREAM_END,
  )
  ```
  Keep `__all__` unchanged. nano→sdk is boundary-legal.
- `packages/soothe/src/soothe/foundation/events/constants.py` — **replace** the
  duplicate literal assignments for these 7 with re-exports from
  `soothe_sdk.core.events`. Keep `__all__` unchanged. Also remove the now-redundant
  self-assignment block (`STRANGE_LOOP_STEP_STARTED = STRANGE_LOOP_STEP_STARTED`
  etc., L122-130) — these are dead self-referential no-ops.

**Do not touch** the orchestration constants (`STRANGE_LOOP_*`, `WIRED_*`,
`INTENT_CLASSIFIED`, `LOOP_CLARIFICATION_*`, `PLAN_CREATED`, `TOOL_*`,
`MESSAGE_*`). Per Decision B3, these stay in the SDK as the protocol-contracts
layer for CLI/Go/TS consumption. B2's scope is only the 7 protocol-primitive
constants that are duplicated across all three files.

### B2. PR-3 — Daemon events constants module

Create `packages/soothe-daemon/src/soothe_daemon/events/constants.py`:
```python
"""Centralized event type string constants for daemon-owned wire events.

Channel and skillify events declared inline in their modules are
canonicalized here. Wire-visible constants consumed across packages
(strange-loop, stream-end) remain in ``soothe_sdk.core.events`` (the
protocol-contracts layer); this module owns only daemon-defined types.
"""
from __future__ import annotations

# Channel (soothe.channel.*)
CHANNEL_MESSAGE_RECEIVED = "soothe.channel.message.received"

# Output (soothe.output.*)
OUTPUT_TEXT_COMPLETE = "soothe.output.text.complete"
OUTPUT_TEXT_DELTA = "soothe.output.text.delta"
OUTPUT_TEXT_END = "soothe.output.text.end"
OUTPUT_UI_RENDER = "soothe.output.ui.render"
OUTPUT_PROGRESS = "soothe.output.progress"
OUTPUT_REASONING = "soothe.output.reasoning"

# Skillify (soothe.skillify.*)
SKILLIFY_RETRIEVE_COMPLETED = "soothe.skillify.retrieve_completed"
SKILLIFY_INDEX_STARTED = "soothe.skillify.index_started"
SKILLIFY_INDEX_UPDATED = "soothe.skillify.index_updated"
SKILLIFY_INDEX_UNCHANGED = "soothe.skillify.index_unchanged"
SKILLIFY_INDEX_FAILED = "soothe.skillify.index_failed"

__all__ = [...]
```
- `packages/soothe-daemon/src/soothe_daemon/channels/events.py` — replace
  inline `type: str = "soothe.channel.message.received"` etc. with
  `from soothe_daemon.events.constants import CHANNEL_MESSAGE_RECEIVED` and
  `type: str = CHANNEL_MESSAGE_RECEIVED`.
- `packages/soothe-daemon/src/soothe_daemon/skillify/events.py` — replace the
  inline `SKILLIFY_*` literal assignments with imports from the new module.
- Add `soothe_daemon/events/__init__.py` re-exporting the constants if a
  package-level convenience import is conventional (match host pattern).

Note: the skillify snake-glue names (`retrieve_completed`, `index_started`) are
**kept as-is** in this IG — renaming them is C-series (deferred). This PR only
centralizes; it does not rename.

### B3. Verification (PR-2, PR-3)

- `./scripts/verify_finally.sh` green.
- `python scripts/check_nano_duplicate_symbols.py` — 0 (nano constants now
  re-export, not redefine; no collision with host).
- `python -c "from soothe_nano.events import STREAM_END, ERROR; from soothe.foundation.events import STREAM_END, ERROR; assert soothe_nano.events.STREAM_END is soothe_sdk.core.events.STREAM_END"` — same object identity (re-export, not redefinition).
- Daemon: `python -c "from soothe_daemon.channels.events import ChannelMessageReceived; print(ChannelMessageReceived.type)"` resolves via the new constant.

---

## Workstream D — Dead veritas events removal

### D0. Verification (locked)

`VeritasRequestedEvent` / `VeritasAnsweredEvent` / `VeritasDeferredEvent`
(host `subagents/veritas/events.py`) have zero construction sites in non-test
code (confirmed by repo-wide grep). The live clarification relay uses the
`sloop/clarification/events.py` `Clarification*` events under
`soothe.loop.clarification.*`. The veritas events under
`soothe.subagent.veritas.*` are registered but never emitted.

### D1. PR-4 — Remove dead veritas events

Files:
- `packages/soothe/src/soothe/subagents/veritas/events.py` — **delete** the
  3 event classes, the 3 `SUBAGENT_VERITAS_*` constants, the 3 `register_event`
  calls, and the `__all__` entries.
- `packages/soothe/src/soothe/subagents/veritas/__init__.py` — remove the
  `SUBAGENT_VERITAS_*` re-exports (L11-13, L24-26).
- Grep for any remaining `SUBAGENT_VERITAS_*` / `VeritasRequestedEvent`
  references in non-test code; remove or repoint. (Test references in
  `packages/soothe-sdk/tests/unit/ux/` reference the *string*
  `"soothe.subagent.veritas.requested"` for classifier tests — **keep** those;
  they test the classifier's string handling, not the dead model. Verify the
  classifier doesn't depend on the model being registered.)

**Pre-check**: `grep -rn "SUBAGENT_VERITAS\|VeritasRequestedEvent\|VeritasAnsweredEvent\|VeritasDeferredEvent" packages/` (excluding tests) must show only the definition files before deletion.

### D2. Verification (PR-4)

- `./scripts/verify_finally.sh` green.
- Vulture reports no new dead code (the deletion *removes* dead code; ensure
  no orphaned imports remain).
- `python -c "import soothe.subagents.veritas"` succeeds (no broken `__init__`).

---

## Execution order & PR plan

| PR | Workstream | Scope | Wire change? |
|----|------------|-------|--------------|
| PR-1 | A1 + A2 | 6 models → nano sole owner; host imports; `custom_event`/`StreamChunk` consolidated | No |
| PR-2 | B1 | 7 primitive constants → SDK canonical; nano + host re-export | No |
| PR-3 | B2 | Daemon `events/constants.py` module; channel + skillify repoint | No |
| PR-4 | D1 | Dead veritas events removed | No |

Each PR is independently verifiable and can land separately. Recommended order:
PR-2 first (constants canonical — unblocks PR-1's import wiring), then PR-1,
then PR-3, then PR-4. Run `./scripts/verify_finally.sh` + both boundary
checkers after each PR.

## Per-PR verification checklist (applies to all PRs)

1. `./scripts/verify_finally.sh` — zero lint errors, all tests pass, vulture clean.
2. `python scripts/check_nano_duplicate_symbols.py` — exit 0.
3. `python scripts/check_nano_docstring_refs.py` — exit 0.
4. `bash scripts/check_module_import_boundaries.sh` — exit 0 (rules 1-4, 3b, 3c).
5. No new wire strings emitted: `git diff` shows no changes to any string
   literal matching `"soothe\..*"` (only import rebinding + deletions).
6. `uv sync --all-packages --all-extras` succeeds (workspace integrity).

## Non-goals (explicit)

- No wire-string renames (C1–C4) — deferred to follow-up RFC.
- No moving orchestration constants out of the SDK (B3 "full move" rejected —
  CLI layering).
- No client submodule changes (Go/TS/Python) — zero wire change means no client
  coordination needed.
- No verbosity/priority/summary-template changes — only ownership moves.
- No `REPLAY_COMPLETE` change (intentional envelope marker).

## Risk

- **Circular import** (PR-1): host `foundation/events/catalog.py` importing
  from `soothe_nano.events.catalog` while host already imports nano modules at
  the file's bottom. Mitigate: place the import at the top of catalog.py with
  the other `from soothe_sdk...` imports; nano's catalog imports only from
  `soothe_sdk`, not from host, so no cycle. Verify with
  `python -c "import soothe.foundation.events.catalog"`.
- **Regression in `isinstance` checks** (PR-1): any code doing
  `isinstance(e, host.MemoryRecalledEvent)` before the move will now check
  against the nano class. Since host's class was a dead duplicate never
  constructed, the only live instances were already nano's — behavior unchanged.
  Verify with grep for `isinstance.*MemoryRecalledEvent` etc.
- **Daemon `events/` package creation** (PR-3): ensure no name collision with
  an existing `soothe_daemon.events` module/attr. Pre-check:
  `ls packages/soothe-daemon/src/soothe_daemon/ | grep events`.
