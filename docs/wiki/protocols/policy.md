---
title: "PolicyProtocol"
parent: Protocols
grand_parent: Wiki
nav_order: 4
description: Permission-based access control protocol for security boundaries and least-privilege delegation.
---

# PolicyProtocol

**RFC**: 305 (Protocol Specifications series)
**Location**: `packages/soothe/src/soothe/protocols/policy.py` (re-exported from `packages/soothe-sdk/src/soothe_sdk/protocols/policy.py`)
**Status**: Implemented

## What PolicyProtocol Is

PolicyProtocol defines the interface for **permission-based access control** in Soothe. It implements the least-privilege delegation principle (RFC-000 Principle 7): before any action — a tool call, a subagent spawn, an MCP connection — the runtime asks PolicyProtocol "is this permitted?" and proceeds only on an `allow` verdict.

The protocol is defined in the SDK package (`soothe_sdk`) for reusability and re-exported from the main `soothe` package for backwards compatibility.

## Why It Exists

Agent systems that execute shell commands, write files, and spawn subagents need guardrails. Without a centralized permission system, security checks scatter across tool implementations, becoming inconsistent and hard to audit. PolicyProtocol centralizes:

- **Permission enforcement** — a single chokepoint for all action checks
- **Least-privilege delegation** — subagents inherit *narrower* permissions than their parent
- **Structured permissions** — category + action + scope granularity, not opaque strings
- **Profile-based configuration** — named profiles (`readonly`, `standard`, `privileged`) that users select
- **Approval workflow** — `allow` / `deny` / `need_approval` verdicts enable interactive confirmation

## Key Operations

- **`check(action, context) → PolicyDecision`** — evaluate whether an action is permitted under the current context. Returns a verdict (`allow` / `deny` / `need_approval`) with a human-readable reason and the matched permission (if allowed).
- **`narrow_for_child(parent_permissions, child_name) → PermissionSet`** — compute a narrowed permission set for a child subagent. Children can never exceed parent permissions (intersection semantics).

## The Permission Model

### Structured Permissions

Permissions are three-part: `Permission(category, action, scope)`.

- **Category**: `fs` (filesystem), `shell`, `net` (network), `mcp` (MCP servers), `subagent`
- **Action**: `read`, `write`, `execute`, `connect`, `spawn`
- **Scope**: `*` (all), glob patterns (`/tmp/**`), specific names (`ls`), or exclusion (`!rm`)

This structure is clearer than flat strings (`fs_read_tmp`) and enables grouping, glob matching, and deny semantics.

### Scope Patterns

| Pattern | Meaning |
|---------|---------|
| `*` | All items in the category |
| `/project/**` | Glob — any path under /project |
| `ls` | Specific item (exact match) |
| `!rm` | Exclusion — anything *except* `rm` |

Exclusion patterns (`!`) are how deny semantics work: grant `shell:execute:*` and `shell:execute:!rm` together means "all commands except `rm`."

### PermissionSet

`PermissionSet` is an immutable collection of `Permission` grants with scope-aware matching. `contains(requested)` returns `True` if *any* granted permission covers the request. `narrow(allowed)` returns a subset for child delegation (set intersection).

### PolicyDecision

The verdict has three states:

- **`allow`** — proceed; includes the matched permission and reason
- **`deny`** — block; includes the reason
- **`need_approval`** — pause for user confirmation; the action would be permitted *if approved*

The `need_approval` flow enables interactive security: dangerous operations (e.g., `rm -rf`) can be configured as approvable rather than hard-denied, letting users make case-by-case decisions.

## Permission Narrowing

The least-privilege principle in action:

```
Parent (depth=0, profile=standard):
  → PermissionSet: [fs:read:*, shell:execute:*, ...]

Child Subagent (depth=1):
  → Narrowed to allowed subset (intersection)
  → Cannot exceed parent permissions

Grandchild Subagent (depth=2):
  → Further narrowed
  → Delegation depth tracked for auditing
```

Children get an *intersection* of the parent's permissions and the allowed set. This is a one-way ratchet: permissions only narrow, never expand. Delegation depth is tracked for audit trails.

## Profile-Based Configuration

Profiles are named bundles of permissions:

- **`readonly`** — `fs:read:*`, `shell:execute:ls`, `shell:execute:cat`. No modifications.
- **`standard`** — `fs:read:*`, `fs:write:/tmp/**`, `shell:execute:*` except `rm`, `mcp:connect:*`, `subagent:spawn:*`. Standard development access.
- **`privileged`** — `*:*:*`. Full access (dangerous).

Profiles also carry `approvable` (permissions that can be interactively approved) and `deny_rules` (explicit denies that override grants). `PolicyProfile` bundles these into a named, reusable configuration.

## Backend: ConfigDrivenPolicy

The current implementation, driven by YAML configuration. Features:

- YAML-based profile definitions (see `config/nano.template.yml`)
- Permission inheritance and narrowing for subagents
- Approval workflow support
- Delegation depth tracking

Resolved via `resolve_policy(config)` → returns a `PolicyProtocol` instance.

## Integration Points

### Policy ↔ Enforcement Middleware

Policy decisions are enforced via `PolicyEnforcementMiddleware`, which intercepts tool calls and subagent spawns:

```
Before each action:
  1. Create ActionRequest from the operation
  2. Call policy.check(request, context)
  3. allow → proceed
  4. deny → raise PermissionError
  5. need_approval → pause for user input
```

### Policy ↔ Durability

Threads carry a `policy_profile` in their `ThreadMetadata`. A thread created with `policy_profile="readonly"` enforces read-only permissions for its entire lifetime. The profile is set at creation and applies to all operations within the thread. See [durability.md](durability.md).

### Policy ↔ Subagent Delegation

When a subagent is spawned, the runtime calls `narrow_for_child()` to compute the child's permission set. The child receives a `PolicyContext` with the narrowed permissions and an incremented delegation depth. The child's own `check()` calls use this narrowed set — it physically cannot perform actions outside its scope.

### Policy ↔ OperationSecurity

`OperationSecurityProtocol` (see [loop-protocols.md](loop-protocols.md)) normalizes concrete operations into security requests and can delegate to `PolicyProtocol` for permission matching. Policy is the decision engine; operation security is the operation-aware wrapper.

## Design Rationale

### Why Structured Permissions?

Flat string permissions (`fs_read_tmp`) lack granularity and are hard to match. The category/action/scope split enables:
- Grouping by category (all `fs` permissions)
- Glob scope matching (`/tmp/**` covers `/tmp/a/b/c`)
- Exclusion semantics (`!rm` for deny)
- Clear audit trails (which grant matched which request)

### Why Permission Narrowing?

The least-privilege principle (RFC-000 Principle 7) demands that delegated agents can't exceed their delegator's power. Intersection semantics guarantee this: a child's permissions are always a subset of the parent's. Delegation depth tracking provides audit visibility into how far down the chain a permission propagated.

### Why Profile-Based?

Named profiles (`readonly`, `standard`, `privileged`) are far more intuitive than raw permission lists. Users select a profile by name; they don't construct permission sets manually. Profiles are reusable across threads and deployments, making security configuration consistent and reviewable.

## Gotchas

- **Deny rules override grants** — a `deny_rules` entry in a profile takes precedence over any matching grant, even if the grant is broader. Always check deny rules when debugging unexpected denials.
- **`need_approval` blocks execution** — if no approval mechanism is wired up, `need_approval` effectively becomes a deny. Ensure the enforcement middleware handles the approval flow.
- **Narrowing is intersection, not union** — `narrow(allowed)` returns `parent ∩ allowed`, not `parent ∪ allowed`. If `allowed` contains permissions the parent doesn't have, those are silently dropped.
- **Exclusion scope is per-permission** — `shell:execute:!rm` only denies `rm`. You still need `shell:execute:*` (or specific allows) for other commands to work.
- **Profiles are defined in SDK** — the `PolicyProtocol` and its data models live in `soothe_sdk.protocols.policy`. The `soothe.protocols.policy` module re-exports them. Import from either; the SDK path is canonical.

## Specification Reference

- **RFC-305**: Policy Protocol Architecture
- **RFC-102**: Security Filesystem Policy
- **RFC-000**: System Conceptual Design (Principle 7: least-privilege)

## Related Documentation

- **[Policy Backends](../backends/policy-backends.md)** — Backend implementations
- [Loop Protocols](loop-protocols.md) — `OperationSecurityProtocol` wraps policy
- [Durability Protocol](durability.md) — `policy_profile` in thread metadata
- [Execution Protocols](execution-protocols.md) — enforcement during runs
