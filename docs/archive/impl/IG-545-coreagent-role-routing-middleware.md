# IG-545: CoreAgent Role Routing Middleware

**IG**: 545  
**Title**: CoreAgent Role Routing Middleware  
**Created**: 2026-07-03  
**Related RFCs**: RFC-627 (LLM factory / ModelRouter)  
**Status**: Implemented

## Summary

Add opt-in `RoleRoutingMiddleware` so the CoreAgent ReAct loop can use different `ModelRouter` roles per model hop: a cheap **orchestration** role (default `fast`) for early tool-planning hops, and a stronger **generation** role (default `default`) for synthesis and later hops.

## Motivation

`create_deep_agent` binds one base model for the entire Model → Tools → Model loop. Soothe already routes roles at component boundaries (intent classify, subagents, StrangeLoop plan assess), but not inside CoreAgent hops. Users want:

| Phase | Typical need | Router role |
|-------|----------------|-------------|
| Tool orchestration | Fast tool selection, low cost | `fast` |
| Content / code generation | Higher quality final output | `default` / `think` |

LangChain `AgentMiddleware.wrap_model_call` is the extension point (`ModelRequest.override(model=...)`). `PerTurnModelMiddleware` already swaps models per stream; this generalizes to per-hop role selection.

## Design

### Config (`agent.runtime.role_routing`)

```yaml
agent:
  runtime:
    role_routing:
      enabled: false                    # opt-in
      orchestration_model_role: fast
      generation_model_role: default
      max_orchestration_hops: 1         # fast model for first N hops per user message
```

### Routing rules (generation role)

Use `generation_model_role` when **any** of:

1. `request.tools` is empty (e.g. goal synthesis after `SystemPromptMiddleware` strips tools).
2. LangGraph configurable `soothe_goal_synthesis` is true.
3. `request.tool_choice == "none"`.
4. Model hop index since last `HumanMessage` ≥ `max_orchestration_hops`.

Otherwise use `orchestration_model_role`.

**Hop index**: count of `AIMessage` instances after the last `HumanMessage` in `request.messages` (0 = first model call for the user turn).

### Middleware placement

Insert **immediately before** `PerTurnModelMiddleware` (inner stack). Stream-level daemon/TUI overrides still win.

### Limitations (documented)

- When tools remain bound on later hops, hop cap controls when to switch — not a perfect oracle for “one more tool vs final answer”.
- Orchestration and generation roles that resolve to the same `provider:model` are a no-op swap.
- Disabled by default to avoid behavior change for existing deployments.

## Files

| File | Action |
|------|--------|
| `docs/impl/IG-545-coreagent-role-routing-middleware.md` | Create — this document |
| `packages/soothe/src/soothe/config/models.py` | Add `RoleRoutingConfig`, wire into `AgentRuntimeConfig` |
| `packages/soothe/src/soothe/middleware/role_routing.py` | Create middleware |
| `packages/soothe/src/soothe/middleware/_builder.py` | Mount when enabled |
| `config/config.template.yml` | Document defaults |
| `config/develop/config.yml` | Mirror structure |
| `packages/soothe/tests/unit/middleware/test_role_routing.py` | Unit tests |

## Verification

```bash
./scripts/verify_finally.sh
```
