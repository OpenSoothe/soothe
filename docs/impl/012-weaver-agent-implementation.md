# Weaver Agent Implementation Guide

**Guide**: IG-012
**Title**: Weaver Agent Implementation
**Created**: 2026-03-13
**Related RFCs**: RFC-0001, RFC-0002, RFC-0003, RFC-0004, RFC-0005

## Overview

This guide describes implementation of Weaver, a subagent generation framework that composes Skillify results, tools, and MCP resources into instant Soothe-compatible generated subagents. It focuses on safe reuse-first generation and durable registration.

## Prerequisites

- [x] RFC-0001 available
- [x] RFC-0002 available
- [x] RFC-0003 available
- [x] RFC-0004 drafted (Skillify)
- [x] RFC-0005 drafted (Weaver)

## Deliverables

| Area | Deliverable |
|------|-------------|
| Analysis | Requirement-to-capability signature planner |
| Reuse | Generated-agent search/index with confidence scoring |
| Composition | Skill/tool/MCP dependency resolver |
| Generation | `create-subagent` workflow integration |
| Registry | Durable metadata store + route publication |

## Suggested File Structure

```text
src/soothe/subagents/weaver.py                # Weaver SubAgent/CompiledSubAgent
src/soothe/weaver/
  analyzer.py                                 # requirement analysis
  reuse_index.py                              # generated agent semantic index
  composer.py                                 # skill/tool/mcp composition
  generator.py                                # create-subagent execution flow
  registry.py                                 # generated-agent registry
```

## Implementation Plan

### Phase 1: Config and scaffolding

- Add `weaver` section in `SootheConfig`
- Add workspace defaults under `~/.soothe/agents/weaver/`
- Register Weaver in subagent routing map

### Phase 2: Requirement analysis + reuse index

- Implement capability signature extraction from user requests
- Build reusable-agent metadata schema (capabilities, constraints, version)
- Add semantic lookup for candidate reuse with confidence threshold

### Phase 3: Composition graph

- Retrieve relevant skills from Skillify service
- Resolve tool dependencies from existing Soothe tool groups
- Resolve MCP requirements via `langchain-mcp-adapters` configuration
- Generate composition plan with explicit permissions requested

### Phase 4: Subagent generation and validation

- Execute bundled `create-subagent` skill using composition plan
- Enforce output structure checks and runnable entry requirements
- Perform policy checks before registration/publication

### Phase 5: Registry + runtime integration

- Register generated agents with metadata, version, and workspace path
- Index generated agents for future reuse-first behavior
- Emit `soothe.weaver.*` events and integrate with runner observability

## Testing Strategy

### Unit tests

- Requirement analyzer capability extraction
- Reuse scoring and threshold behavior
- Composition plan includes required skills/tools/MCPs
- Registry versioning and retrieval consistency

### Integration tests

- Reuse hit path returns existing agent without generation
- Reuse miss path generates and registers new agent
- Policy denial prevents restricted tool/MCP inclusion
- Generated agent loads through standard Soothe routing path

## Verification Checklist

- [ ] Weaver is available as a routable Soothe subagent
- [ ] Reuse-first logic works with configurable threshold
- [ ] Generation uses bundled `create-subagent` skill flow
- [ ] MCP integration path uses langchain adapters only
- [ ] Generated agents are durable, indexed, and discoverable
- [ ] Policy and observability checks are present for all sensitive actions

## Rollout Notes

- Start with internal-only generation and constrained tool set.
- Expand allowed MCP/tool scope incrementally based on policy maturity.
- Periodically re-index generated agents to improve reuse precision.

## Related Documents

- [RFC-0005](../specs/RFC-0005.md) - Weaver Agent Architecture Design
- [RFC-0004](../specs/RFC-0004.md) - Skillify Agent Architecture Design
- [IG-011](./011-skillify-agent-implementation.md) - Skillify Agent Implementation
