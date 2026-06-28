# Policy Backends

Permission-based access control via `PolicyProtocol`. Policy backends enforce security boundaries, filesystem access rules, and least-privilege delegation across Soothe's execution. They determine whether each action (file read, shell command, network call, subagent spawn) is allowed, denied, or requires interactive approval.

---

## What Policy Backends Do

Policy backends answer one question for every action: *should this be allowed?* The two core operations are:

- **`check(action, context)`** — Evaluate an `ActionRequest` against the active `PermissionSet` and return a `PolicyDecision` (`allow`, `deny`, or `need_approval`).
- **`narrow_for_child(parent_permissions, child_name)`** — Compute a narrowed permission set for a subagent, enforcing least-privilege delegation.

The policy layer is **not optional** — it's enforced via middleware (`PolicyEnforcementMiddleware`) that intercepts tool calls before execution. Every filesystem read, shell command, and network connection passes through policy evaluation.

---

## Permission Model

Permissions use a structured `category:action:scope` format with glob and negation support.

### Permission Categories

| Category | Actions | Scope Examples |
|----------|---------|----------------|
| `fs` | `read`, `write` | `*` (all), `/tmp/**` (glob), `/home/user/**` |
| `shell` | `execute` | `ls` (only ls), `!rm` (anything except rm) |
| `net` | `outbound` | `*.example.com`, `*` |
| `mcp` | `connect`, `invoke`, `read_resource` | server name |
| `subagent` | `spawn` | subagent name |

**Matching semantics**: Glob patterns for paths (`/tmp/**` matches all files under `/tmp/`); command names for shell (exact match or negation with `!`); domain globs for network.

**Permission extraction**: The policy backend automatically extracts the required permission from an `ActionRequest`. For tool calls, it inspects tool metadata to determine category (file_ops → `fs`, execution → `shell`) and extracts the relevant scope (filesystem path, command name).

---

## Available Backends

### ConfigDrivenPolicy

The sole `PolicyProtocol` implementation — configuration-driven policy with named profiles, deny rules, and interactive approval.

**Evaluation order** (critical to understand):

1. **Operation security check** (for tool calls only) — `WorkspaceToolOperationSecurity` validates filesystem paths and shell commands against workspace boundaries *before* permission checks. If this denies, policy stops here.
2. **Deny rules** — Explicit deny rules in the profile are checked first. If any deny rule matches, the action is denied immediately (deny overrides grant).
3. **Granted permissions** — If the active `PermissionSet` contains the required permission, the action is allowed.
4. **Approvable set** — If the required permission is in the profile's `approvable` set, the verdict is `need_approval` (interactive approval required).
5. **Default deny** — If none of the above match, the action is denied.

**Key characteristics**:
- **Profile-based**: Policies are named profiles (`readonly`, `standard`, `privileged`) each with a `PermissionSet`, `approvable` set, and `deny_rules`.
- **Least-privilege delegation**: `narrow_for_child()` intersects parent permissions with per-child restrictions. A child can never have *more* permissions than its parent.
- **Per-child overrides**: `child_restrictions` map allows further restricting specific subagents (e.g., `explore` gets only `fs:read:*`).
- **Operation security integration**: Filesystem path validation and shell command extraction happen before permission matching.

**When to use**: This is the only policy backend. The decision is *which profile* to use, not *which backend*.

**Minimal config**:
```yaml
agent:
  protocols:
    policy:
      enabled: true
      profile: standard    # readonly, standard, or privileged
```

Source: `packages/soothe/src/soothe/foundation/core/security/config_policy.py`

---

## Built-in Profiles

Three profiles ship with ConfigDrivenPolicy:

| Profile | Granted Permissions | Approvable | Use Case |
|---------|---------------------|------------|----------|
| **readonly** | `fs:read:*`, `net:outbound:*`, `subagent:spawn:*` | `fs:write:*`, `shell:execute:*` | Read-only analysis; writes need approval |
| **standard** | Full read/write/execute/net/mcp/subagent | None (empty set) | Default development profile |
| **privileged** | Same as standard | None | No approval restrictions |

**Key insight**: `readonly` is the only profile with `approvable` permissions — write and execute actions require interactive approval. `standard` and `privileged` grant everything but differ in whether approval is ever requested (neither has approvable permissions, so the distinction is structural).

**Custom profiles**: You can define custom profiles by passing a `dict[str, PolicyProfile]` to the constructor, overriding `DEFAULT_PROFILES`.

---

## Least-Privilege Delegation

Soothe enforces least-privilege: subagents receive a *narrowed subset* of the parent's permissions.

**How it works**: `narrow_for_child()` intersects the parent's `PermissionSet` with the child's allowed permissions. The child can only retain permissions that exist in *both* sets — it's a strict intersection, never an expansion.

**Per-child restrictions**: The `child_restrictions` map allows specifying a `frozenset[Permission]` per child name. If a child name is in the map, the parent's permissions are narrowed to the intersection with that frozenset. Children not in the map inherit the parent's permissions unchanged.

**Delegation depth**: There is no explicit depth limit, but each narrowing can only reduce permissions. A chain of delegations naturally converges toward an empty permission set.

---

## Sandbox Enforcement

ConfigDrivenPolicy integrates with `WorkspaceToolOperationSecurity` for defense-in-depth:

- **Filesystem path validation**: Extracts paths from tool arguments and validates them against workspace boundaries. Paths outside the workspace root are denied (unless explicitly allowed via `allow_paths_outside_workspace`).
- **Shell command extraction**: Extracts the command name from tool arguments for permission matching (e.g., `git push` → `shell:execute:git`).
- **Denied paths/file types**: Configuration-level deny lists (e.g., `/etc`, `*.env`, `*.pem`) are checked during operation security evaluation, before permission matching.

This means policy enforcement happens at two layers: operation security (workspace/path/command validation) and permission matching (category/action/scope). Both must pass for an action to be allowed.

---

## Performance Characteristics

| Operation | Latency | Notes |
|-----------|---------|-------|
| `check()` | ~5-15ms | Permission extraction + set matching |
| `narrow_for_child()` | ~1-5ms | Frozenset intersection |
| Profile lookup | ~1-2ms | Dict lookup by permission set |

**Policy checks are fast** because they're pure in-memory set operations — no I/O, no network. The main cost is permission extraction (inspecting tool arguments), which varies by action type.

**Optimization**: Cache policy decisions per context (same action + same context → same verdict). Pre-compile wildcard patterns. Minimize rule count — each deny rule adds a matching pass.

---

## Production Gotchas

1. **Deny rules override grants**: A deny rule matching an action *always* denies, even if the permission is explicitly granted. This is by design (safety-first) but can cause confusion if deny rules are too broad.

2. **Operation security runs first**: For tool calls, `WorkspaceToolOperationSecurity` evaluates before permission matching. A path outside the workspace is denied regardless of `fs:write:*` grants. Configure `allow_paths_outside_workspace` if you need writes outside the workspace.

3. **`need_approval` blocks execution**: Actions requiring approval pause execution until approved. In autonomous (non-interactive) mode, these effectively become denials. Ensure the active profile's `approvable` set is empty for autonomous workflows.

4. **Child restriction is intersection, not replacement**: `narrow_for_child()` intersects parent permissions with child restrictions. If the parent doesn't have a permission, the child can't get it via restrictions — restrictions can only *reduce*, never *grant*.

5. **Profile selection by permission set**: `_find_profile()` matches the active `PermissionSet` against known profiles. If no profile matches, deny rules and approvable checks are skipped — only grant-based matching applies. Ensure your custom profiles are discoverable.

6. **Policy is enforced via middleware, not direct calls**: `FrameworkFilesystem` and other tools don't call `policy.check()` directly. The `PolicyEnforcementMiddleware` intercepts tool calls and enforces policy transparently. This means policy applies to *all* tool calls, not just filesystem operations.

---

## Related Documentation

- **[Backends Overview](README.md)** — Backend layer introduction
- **[Workspace Management](../core/workspace.md)** — Workspace security boundaries
- **[RFC-102](../../specs/RFC-102-security-filesystem-policy.md)** — Security policy spec
- **[RFC-001](../../specs/RFC-001-core-modules-architecture.md)** — Policy protocol spec
