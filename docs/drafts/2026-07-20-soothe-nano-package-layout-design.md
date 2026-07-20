# Design Draft: soothe-nano Package Layout

**Status**: Approved → impl [IG-668](../impl/IG-668-soothe-nano-package-extract.md)  
**Date**: 2026-07-20  
**Scope**: Extract batteries-included Coding CoreAgent into `soothe-nano`; full `soothe` depends on it. No StrangeLoop, Autopilot, Context Engine, cron, or daemon in nano.  
**Related**: [RFC-000](../specs/RFC-000-system-conceptual-design.md), [RFC-100](../specs/RFC-100-coreagent-runtime.md), [RFC-001](../specs/RFC-001-core-modules-architecture.md)

---

## Decisions (locked)

| Decision | Choice |
|----------|--------|
| Product shape | Drop-in CoreAgent for full soothe (not a separate UX product) |
| Scope | Batteries-included: factory + toolkits + core subagents + skills + MCP + slim config |
| Layout | Clean product tree under `soothe_nano/` (Approach B), not a mirror extract |
| Dependency rule | `soothe-nano` never imports `soothe`; `soothe` depends on `soothe-nano` |

## Dependency stack

```
soothe-deepagents
soothe-sdk
soothe-nano          # Coding CoreAgent + tools/subagents/skills/MCP
soothe               # StrangeLoop, Autopilot, CE, cron, identity, runner
soothe-daemon / soothe-cli
soothe-plugins       # prefer soothe-nano (later phase)
```

## Package tree

```
packages/soothe-nano/
  src/soothe_nano/
    agent/           # CodingCoreAgent, builder, factory, lazy
    config/          # NanoConfig (subset; SootheConfig extends)
    toolkits/
    subagents/       # explore, plan, deep_research, academic_research
    middleware/
    skills/
    mcp/
    filesystem/
    security/
    workspace/
    protocols/       # CoreAgentCapabilities + optional hooks
    resolve/         # resolve_tools / resolve_subagents
    utils/
  tests/{unit,integration}/
```

## Gray zones (defaults)

- `browser_use` / `veritas`: optional extras or `soothe-plugins` (keep nano lean).
- Plugin host: minimal registry hooks in nano; full host stays in soothe.
- Identity: optional `identity_runtime` inject; IdentityService stays in soothe.
- Memory / planner / policy: protocols + inject in nano; heavy backends stay in soothe.

## Phased delivery

See [IG-668](../impl/IG-668-soothe-nano-package-extract.md).

## Exit criteria (design)

- [x] Approach B approved
- [x] Batteries-included boundary approved
- [x] Drop-in-for-soothe product shape approved
