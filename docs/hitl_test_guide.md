# HITL (Human-in-the-Loop) Test Guide

## What is HITL?

HITL pauses the agent before executing certain tools, showing an approval menu in the TUI with options:
- **Approve (y/1)**: Execute the tool call
- **Auto-approve all (a/2)**: Approve this and all subsequent tools in this loop
- **Reject (n/3)**: Block the tool and inform the agent

## Configuration

Enable HITL in your config file:

```yaml
hitl:
  enabled: true
  tools: ["execute", "write_file", "edit_file", "delete_file"]
```

**Tool name normalization**: `bash`, `shell`, `execute` all map to the shell execution tool.

## Test Cases

### Test 1: Shell Command Approval

1. Start TUI: `soothe`
2. Ask: "List files in current directory"
3. **Expected**: ApprovalMenu appears showing the `execute` tool with command preview
4. Press `y` to approve
5. **Expected**: Command executes, agent shows results

### Test 2: Reject Shell Command

1. Ask: "Delete all files in the workspace"
2. **Expected**: ApprovalMenu appears for `execute rm ...` or similar
3. Press `n` to reject
4. **Expected**: Tool rejected, agent receives error message and adapts

### Test 3: Auto-Approve All

1. Ask: "List all Python files and show the README"
2. ApprovalMenu appears for first `execute` command
3. Press `a` for auto-approve-all
4. **Expected**: Subsequent tool calls in this loop auto-execute without prompts

### Test 4: File Write Approval

1. Ask: "Create a file called test.txt with hello world content"
2. **Expected**: ApprovalMenu shows `write_file` tool with path and content preview
3. Approve and verify file is created

### Test 5: Edit File Approval

1. Ask: "Change the first line of test.txt to 'goodbye'"
2. **Expected**: ApprovalMenu shows `edit_file` tool with diff preview
3. Approve and verify file is edited

### Test 6: HITL Disabled

1. Edit config: `hitl.enabled: false`
2. Ask multiple shell/file operations
3. **Expected**: No approval prompts, all tools execute directly

## Verification Checklist

- [ ] Config loads without validation errors
- [ ] Daemon starts with `hitl.enabled: true`
- [ ] ApprovalMenu appears for configured tools
- [ ] Approve (y) executes the tool
- [ ] Reject (n) blocks the tool and agent adapts
- [ ] Auto-approve all (a) skips subsequent prompts
- [ ] Shell commands use `execute` tool name (aliases normalized)
- [ ] `enabled: false` disables all prompts

## Implementation Notes

**Flow**:
1. Agent emits tool call for `execute` (shell)
2. `HumanInTheLoopMiddleware` (deepagents) intercepts
3. LangGraph emits `__interrupt__` in updates stream
4. TUI `_turn.py` detects interrupt, validates payload
5. `_request_approval()` mounts `ApprovalMenu` widget
6. User decision → `resume_payload` → `Command(resume=...)`
7. Graph continues with approved/rejected tool

**Files**:
- Config: `config/config.template.yml` → `hitl:` section
- Model: `packages/soothe/src/soothe/config/models.py` → `HitlApprovalConfig`
- Builder: `packages/soothe/src/soothe/core/agent/_builder.py` → `_resolve_interrupt_on()`
- TUI: `packages/soothe-cli/src/soothe_cli/tui/widgets/approval.py` → `ApprovalMenu`
- Turn: `packages/soothe-cli/src/soothe_cli/tui/textual_adapter/_turn.py` → interrupt handling