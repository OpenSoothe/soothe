# RFC-617: OperationSecurityProtocol for Workspace and Tool Execution

**RFC**: 617  
**Title**: OperationSecurityProtocol: Unified Workspace and Tool Operation Security  
**Status**: Draft  
**Kind**: Architecture Design  
**Created**: 2026-04-30  
**Dependencies**: RFC-102, RFC-103, RFC-406, RFC-613

---

## Abstract

This RFC introduces `OperationSecurityProtocol`, a dedicated security protocol for operation-level enforcement across filesystem and execution tools. It centralizes security checks that are currently scattered between policy, workspace backend path normalization, and tool-local command guards.

`OperationSecurityProtocol` evaluates normalized operation intents (path access, shell execution, process management) and returns a structured allow/deny/need-approval decision before permission-profile matching proceeds.

---

## Motivation

Current security controls are effective but fragmented:

- Workspace/path checks are implemented in `ConfigDrivenPolicy` and backend path resolution.
- Shell command safety checks are primarily local to `run_command`.
- Equivalent execution surfaces such as `run_background` are not uniformly checked by policy.
- There is no single structured decision record for operation-level security decisions.

This fragmentation increases the chance of drift between tools and makes audits harder.

---

## Design Goals

1. **Single operation-security contract** for filesystem and execution tools.
2. **Workspace-first path enforcement** aligned with RFC-103 dynamic workspace resolution.
3. **Consistent execution risk checks** across all command-bearing tools.
4. **Composable with PolicyProtocol** (operation checks first, permission checks second).
5. **Structured reasoning** for telemetry, approval UX, and troubleshooting.

---

## Protocol Interface

```python
class OperationSecurityProtocol(Protocol):
    def evaluate(
        self,
        request: OperationSecurityRequest,
        context: OperationSecurityContext,
    ) -> OperationSecurityDecision:
        ...
```

### Core Types

- `OperationSecurityRequest`
  - `action_type`: `tool_call`, `subagent_spawn`, `mcp_connect`
  - `tool_name`: tool identifier
  - `tool_args`: original arguments
  - `operation_kind`: normalized operation kind (`filesystem_read`, `filesystem_write`, `shell_execute`, `python_execute`, `process_control`, `generic`)
  - `target_path`: extracted path-like target when available
  - `command`: command string for execution tools when available

- `OperationSecurityContext`
  - `thread_id`: optional thread id
  - `workspace`: optional dynamic workspace root
  - `security_config`: optional security configuration object

- `OperationSecurityDecision`
  - `verdict`: `allow`, `deny`, `need_approval`
  - `reason`: human-readable reason
  - `rule_id`: optional stable rule id for auditing

---

## Evaluation Model

Operation security is evaluated before profile permission matching:

1. Normalize operation kind from tool metadata.
2. Apply operation-specific rules:
   - Filesystem operation -> path and file-type checks (RFC-102 semantics).
   - Execution operation -> command safety deny checks.
3. Return decision:
   - `deny` or `need_approval` short-circuits permission matching.
   - `allow` proceeds to existing `PolicyProtocol` permission checks.

---

## Reference Rules

### Filesystem Rules

- Denied path patterns (`security.denied_paths`) are highest priority.
- Path must match allowed patterns (`security.allowed_paths`).
- Workspace boundary enforced using dynamic workspace (`context.workspace`) first.
- File-type deny and approval lists are applied.

### Execution Rules

- Block explicit destructive command patterns (for example, recursive root deletion and privileged destructive sequences).
- Rules apply consistently to command-bearing tools such as:
  - `execute` / `shell` / `bash` / `run_command`
  - `run_background`

---

## Integration Plan

1. Add `OperationSecurityProtocol` and models in `soothe.protocols`.
2. Add `WorkspaceToolOperationSecurity` implementation in `soothe.core.security`.
3. Update `ConfigDrivenPolicy.check()` to call operation security first for tool calls.
4. Keep existing permission-profile logic unchanged after operation-security pass.
5. Add tests for:
   - Outside workspace path decisions.
   - File type approval decisions.
   - `run_background` and `run_command` command denial parity.

---

## Backward Compatibility

- Existing `PolicyProtocol` public contracts remain unchanged.
- Existing profile names and permission sets remain unchanged.
- New behavior is additive and strengthens pre-existing security decisions.

---

## Security Considerations

- Centralized checks reduce policy drift and bypass risk.
- Dynamic workspace from execution context remains the source of truth for boundary checks.
- Structured `rule_id` enables stable auditing and future allowlist exception workflows.

---

## References

- RFC-102: Secure Filesystem Path Handling and Security Policy
- RFC-103: Thread-Aware Workspace
- RFC-406: PolicyProtocol Architecture
- RFC-613: Explore Agent LLM-Orchestrated Search
