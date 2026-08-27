# Design: Migrate Tool-Approval Safety to Nano's OperationSecurity

**Date**: 2026-08-27
**Status**: Draft
**Depends on**: RFC-622 §9b, IG-766 (Multi-stage tool-approval pipeline)
**Related**: `soothe_nano/security/operation_guard.py`, `soothe_nano/security/path_security.py`

---

## 1. Problem

IG-766 added `tool_safety_check.py` (Stage 2 of the tool-approval pipeline) with
hardcoded `DANGEROUS_FILES`, `DANGEROUS_DIRECTORIES`, and
`DESTRUCTIVE_COMMAND_PATTERNS` constants. This duplicates a subset of what
nano's `WorkspaceToolOperationSecurity` (`operation_guard.py`) already checks
more comprehensively at Layer 1 (pre-HITL `SoothePolicyMiddleware`) and
Layer 3 (tool execution time in `execution.py`).

### Execution flow for a `run_command` tool call

```
Layer 1: SoothePolicyMiddleware (nano) — before HITL
  └─ ConfigDrivenPolicy.check()
     └─ WorkspaceToolOperationSecurity.evaluate()
        ├─ _check_command()  → _BANNED_COMMAND_PATTERNS (17 regex)
        └─ _check_filesystem() → _SENSITIVE_SYSTEM_PATH_PATTERNS, workspace boundary
  → deny: tool call blocked, never reaches HITL
  → allow/need_approval: passes through

Layer 2: HumanInTheLoopMiddleware (deepagents) — emits action_requests
  └─ Our pipeline.evaluate()
     ├─ Stage 1: deny rules (config-driven)
     ├─ Stage 2: safety checks (our tool_safety_check.py) ← OVERLAP
     ├─ Stage 3: allow rules
     └─ Stage 4: veritas LLM

Layer 3: run_command tool (nano) — at execution
  └─ _security_decision() → WorkspaceToolOperationSecurity.evaluate()
```

The pipeline (Layer 2) only fires when Layer 1 already allowed or said
`need_approval`. If nano's `_BANNED_COMMAND_PATTERNS` denies a command
(e.g., `rm -rf /`), the tool call is blocked at Layer 1 — the pipeline never
sees it. Our `tool_safety_check.py` is checking things nano already checked.

### Overlap table

| Our `tool_safety_check.py` | Nano `operation_guard.py` | Redundant? |
|---|---|---|
| `DESTRUCTIVE_COMMAND_PATTERNS` (11 substrings) | `_BANNED_COMMAND_PATTERNS` (17 regex — includes fork bombs, pipe-to-shell, daemon kill) | Partially — nano is more precise and comprehensive |
| `DANGEROUS_FILES` (10: `.bashrc`, `.gitconfig`, `.mcp.json`, ...) | `DANGEROUS_COMPONENTS` in `path_security.py` (8: `.git`, `.svn`, `__pycache__`, ...) | Different scope — neither covers the other |
| `DANGEROUS_DIRECTORIES` (4: `.git`, `.vscode`, `.idea`, `.claude`) | `_SENSITIVE_SYSTEM_PATH_PATTERNS` (6: `/etc/**`, `/bin/**`, ...) | Different scope |
| Path traversal (`..` segments) | `TRAVERSAL_PATTERNS` (10 regex), `_check_workspace_boundary()` | Redundant — nano is far more comprehensive |
| UNC paths (`//server`) | — | Unique to us |

---

## 2. Approach

Replace Stage 2's standalone `tool_safety_check.py` with a call to nano's
`OperationSecurityProtocol`. Delete the duplicated constants from soothe.
Augment nano's constants with the items our standalone checker had that nano
lacks.

```
Stage 2: Safety checks → WorkspaceToolOperationSecurity.evaluate()
  (instead of our standalone tool_safety_check.py)
```

---

## 3. Changes

### 3.1 Nano: augment `operation_guard.py` constants

Add to `_BANNED_COMMAND_PATTERNS`:
- `shred` (bare `shred` command — secure file deletion)
- `rm\s+-r\b` (bare `rm -r` without `-f` — currently only `rm -rf` is caught)

Add to `DANGEROUS_COMPONENTS` in `path_security.py`:
- Shell config files: `.bashrc`, `.bash_profile`, `.zshrc`, `.zprofile`, `.profile`
- Git config files: `.gitconfig`, `.gitmodules`
- Other: `.ripgreprc`, `.mcp.json`, `.claude.json`
- Config directories: `.vscode`, `.idea`, `.claude`

Add UNC path detection to `PathValidator.SUSPICIOUS_PATTERNS`:
- `^//` and `^\\\\` (UNC path defense-in-depth)

### 3.2 Nano: export `build_operation_security_request` helper

Extract the `OperationSecurityRequest` builder from
`ConfigDrivenPolicy._build_operation_security_request` into a standalone
function in `soothe_nano.security.operation_guard`:

```python
def build_operation_security_request(
    tool_name: str,
    tool_args: dict[str, Any],
) -> OperationSecurityRequest:
    """Build an OperationSecurityRequest from a tool name + args.
    
    Uses is_policy_filesystem_tool / extract_filesystem_path_for_policy
    from soothe_sdk.tools.metadata to classify the operation.
    """
```

`ConfigDrivenPolicy._build_operation_security_request` becomes a thin
delegating wrapper — eliminates the private method, keeps backward
compatibility.

### 3.3 Soothe: replace `tool_safety_check.py` with nano call

`tool_approval_pipeline.py` Stage 2 changes from calling our deleted
`check_path_safety` / `check_command_safety` to:

```python
evaluator = WorkspaceToolOperationSecurity()
request = build_operation_security_request(name, dict(args))
ctx = OperationSecurityContext(
    workspace=workspace_root,
    security_config=self._security_config,
)
decision = evaluator.evaluate(request, ctx)
if decision.verdict == "deny":
    return ApprovalResult("reject", "safety_check", decision.reason)
# "allow" or "need_approval" → continue to Stage 3
```

### 3.4 Soothe: delete `tool_safety_check.py`

Remove the file. Update `__init__.py` to drop the exports. Update
`tool_approval_pipeline.py` to remove the import.

### 3.5 Soothe: pipeline gains `security_config`

`ToolApprovalPipeline.__init__` gains a `security_config` parameter
(the `SecurityConfig` from `SootheConfig.security`). The `runtime_factory`
passes `config.security` when constructing the pipeline.

### 3.6 Fail-safe: `security_config is None`

When `security_config` is `None`:
- `WorkspaceToolOperationSecurity._check_filesystem` returns `verdict="allow"` ("No security config")
- `_check_command` still works (banned patterns are hardcoded, don't need config)
- So command safety still fires; only filesystem safety is skipped
- This is acceptable — Stage 1 (deny rules) and Stage 3 (allow rules) still work

---

## 4. What stays in soothe

- `tool_approval_pipeline.py` — the 4-stage evaluator
- `tool_rule_matcher.py` — config-driven pattern matching for deny/allow rules
- `ToolApprovalConfig` with deny_rules/allow_rules — operator-tunable per-project rules
- Veritas slim prompt — LLM fallback for ambiguous cases

## 5. What moves to nano

- `tool_safety_check.py` → deleted; replaced by `WorkspaceToolOperationSecurity.evaluate()` call
- `DANGEROUS_FILES`, `DANGEROUS_DIRECTORIES`, `DESTRUCTIVE_COMMAND_PATTERNS` constants → merged into nano's `DANGEROUS_COMPONENTS` and `_BANNED_COMMAND_PATTERNS`

## 6. What stays as natural-language duplication (acceptable)

The veritas `_TOOL_APPROVAL_SYSTEM_PROMPT` restates safety principles in
natural language for the LLM. This is acceptable — it's instructions to an LLM
making a judgment on ambiguous cases, not code that can be shared or drift.

---

## 7. Safety properties preserved

1. **Deny rules first.** Unchanged — Stage 1 still fires before Stage 2.
2. **Safety checks bypass-immune.** Still true — `WorkspaceToolOperationSecurity` has hardcoded `_BANNED_COMMAND_PATTERNS` and `_SENSITIVE_SYSTEM_PATH_PATTERNS` that cannot be overridden by config. The `security_config` parameter only adds denied/allowed paths on top.
3. **Allow rules never override safety.** Pipeline order unchanged.
4. **Fail-safe on error.** Pipeline's try/except still catches all Stage 2 exceptions and defers to veritas.
5. **Fail-safe on workspace unknown.** When `workspace_root` is `None`, `OperationSecurityContext.workspace` is `None` — filesystem checks return `allow` (no workspace to check against). Command checks still work.
6. **Veritas remains the final guard.** Unchanged.
7. **`delete` never auto-approved.** Unchanged — `delete` is not in default allow rules.

---

## 8. File manifest

| File | Action | Package |
|------|--------|---------|
| `security/operation_guard.py` | edit: add `shred`, `rm -r` patterns; export `build_operation_security_request` | nano |
| `security/path_security.py` | edit: add shell-config files + `.vscode`/`.idea`/`.claude` to `DANGEROUS_COMPONENTS`; add UNC to `SUSPICIOUS_PATTERNS` | nano |
| `security/policy_profiles.py` | edit: `_build_operation_security_request` delegates to standalone | nano |
| `sloop/clarification/tool_approval_pipeline.py` | edit: Stage 2 calls `WorkspaceToolOperationSecurity`; gains `security_config` param | soothe |
| `sloop/clarification/tool_safety_check.py` | delete | soothe |
| `sloop/clarification/__init__.py` | edit: remove `tool_safety_check` exports | soothe |
| `sloop/clarification/runtime_factory.py` | edit: pass `config.security` to pipeline | soothe |
| `tests/.../test_tool_safety_check.py` | delete | soothe |
| `tests/.../test_tool_approval_pipeline.py` | edit: Stage 2 uses nano evaluator; add `security_config=None` fail-safe test | soothe |
| `config/models.py` | edit: update `ToolApprovalConfig` docstring | soothe |
| `docs/specs/RFC-622-coreagent-clarification-relay.md` | edit: §9b.4 references nano constants | docs |
