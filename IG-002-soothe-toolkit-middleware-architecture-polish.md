# IG-002: Polish toolkit and middleware architecture in Soothe

## Context

This note captures an architecture review of:

- `../soothe/packages/soothe/src/soothe`

using the middleware-first design philosophy used in `soothe-deepagents`:

- Tools that need request-time interception, dynamic visibility, prompt injection,
  or cross-turn state should be middleware-owned.
- Stateless reusable tool definitions should be toolkit-owned.

## Current strengths

1. Middleware responsibilities are intentional and ordered in one place:
   `soothe/middleware/_builder.py`.
2. Tool groups are modularized in `soothe/toolkits/*`.
3. Progressive activation state and reducers are explicit
   (`tool_activation`, `skill_activation`, `mcp_activation`).
4. Core agent assembly wires middleware and tools consistently in
   `foundation/coreagent/coding/builder.py`.

## Main structural issues

### 1) Layer inversion: toolkit resolution depends on middleware internals

`file_ops` tools are currently extracted by instantiating
`SootheFilesystemMiddleware` and filtering `middleware.tools`.

Observed in:

- `soothe/toolkits/file_ops.py`
- `soothe/runner/resolver/_resolver_tools.py`

Why this is problematic:

- Toolkit and resolver are coupled to middleware implementation details.
- The same tool list is assembled in multiple places.
- Any middleware-side behavior change can unintentionally break toolkit loading.

### 2) `SystemPromptMiddleware` is overloaded

`soothe/middleware/system_prompt.py` currently owns many concerns:

- prompt assembly
- dynamic tool narrowing (task-only / synthesis)
- progressive deferred tool listing
- progressive skills listing
- deferred MCP listing
- observability side effects (Langfuse hint publication)

Why this is problematic:

- Large blast radius for regressions.
- Hard to test behavior boundaries and ordering guarantees.
- Hard to reason about feature interactions.

### 3) Middleware stack builder is monolithic

`soothe/middleware/_builder.py` has correct sequencing but high centralization:

- feature toggles
- dependency wiring
- ordering policy
- optional instrumentation

Why this is problematic:

- Difficult to safely evolve.
- Small changes require touching a high-risk central function.

### 4) Tool naming/canonicalization logic is scattered

Resolver paths include legacy and canonical names in multiple branches, while
progressive registries and hint middleware also maintain related assumptions.

Why this is problematic:

- Drift risk across resolver, hints, and progressive activation.
- Harder migration toward consistent public tool contracts.

## Target architecture

### A) Tool catalog as single source of truth

Introduce a unified tool catalog boundary:

- toolkit contract:
  - `build_tools(context) -> list[BaseTool]`
  - `descriptors(context) -> list[ToolDescriptor]`
- resolver composes catalog output only.
- middleware can filter/override tools at request time, but does not act as
  toolkit source of truth.

### B) Split filesystem into tool-definition and runtime-policy layers

Keep middleware for runtime interception only, and move surgical tool
definitions into a toolkit/module that both plugin and resolver can call.

Proposed ownership:

- toolkit layer:
  - surgical tool constructors and schemas
  - filesystem operation adapters
- middleware layer:
  - provider-safe tool-message coercion
  - request-time capability gating
  - prompt/runtime context injection
  - eviction and cross-turn behaviors

### C) Decompose `SystemPromptMiddleware`

Split by concern:

1. `PromptAssemblyMiddleware`
2. `ToolEnforcementMiddleware`
3. `ProgressiveListingMiddleware` (tools/skills/MCP listing state transitions)
4. `PromptObservabilityMiddleware`

Benefits:

- isolated tests per concern
- easier ordering guarantees
- less feature coupling

### D) Declarative middleware stack phases

Replace imperative stack assembly with phase-based registration:

- security phase
- tool-state phase
- prompt phase
- llm-governance phase
- execution phase
- model-routing phase

Builder then resolves enabled entries by config and concatenates phases.

## Recommended migration plan

### Phase 1 (low risk): Decouple file ops toolkit from filesystem middleware

1. Add filesystem surgical toolkit module (tool constructors only).
2. Update `toolkits/file_ops.py` to use toolkit module directly.
3. Update resolver `file_ops` branch to use same toolkit module.
4. Keep `SootheFilesystemMiddleware` behavior unchanged.

Success criteria:

- No behavior change in tool names/schema.
- Same tool set available from plugin and resolver.

### Phase 2: Extract enforcement logic from system prompt middleware

1. Move task-only and synthesis tool filtering into dedicated middleware.
2. Keep `SystemPromptMiddleware` focused on prompt generation.
3. Preserve existing middleware ordering semantics.

Success criteria:

- Prompt snapshots unchanged for equivalent state.
- Tool narrowing behavior unchanged.

### Phase 3: Extract progressive listing flows

1. Move AVAILABLE_TOOLS/SKILLS/MCP listing state transitions to dedicated middleware.
2. Keep prompt assembly middleware consuming prepared state only.

Success criteria:

- Same listing output and state reducer behavior.
- Reduced `SystemPromptMiddleware` size and test surface.

### Phase 4: Declarative stack builder

1. Introduce phase registry and middleware registration map.
2. Port `_builder.py` to phase composition.
3. Keep final stack ordering equivalent to current behavior.

Success criteria:

- Deterministic ordering.
- Easier extension with fewer central edits.

## Acceptance checks

1. Resolver and plugin return the same canonical file-op tool set without
   middleware extraction.
2. Middleware tests validate explicit boundaries:
   - prompt assembly only
   - tool narrowing only
   - progressive listing state transitions only
3. Middleware stack order remains stable and documented by phase.
4. Progressive registries and resolver share one canonical tool naming source.

## Non-goals

- Changing user-visible tool names in the same rollout.
- Reworking subagent architecture in this pass.
- Altering deepagents upstream behavior from this repository.
