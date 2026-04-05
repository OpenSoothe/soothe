# IG-053: CLI Command Nesting Refactoring

**Status**: In Progress
**Created**: 2026-03-25
**Author**: Claude
**Replaces**: IG-050 (reverts flattening approach)

## Summary

This implementation guide documents the refactoring of Soothe CLI commands from a hybrid flat/nested structure to a consistent 2-level nested pattern: `soothe <subcommand> <action> [options]`.

## Motivation

### Problem Statement

IG-050 (March 24, 2026) flattened most CLI commands to use action flags, but left daemon commands nested. This created inconsistency:

```bash
# Inconsistent patterns
soothe thread -c <id>      # Flat with flag
soothe daemon start         # Nested
soothe config -i            # Flat with flag
soothe agent --status       # Flat with flag
```

Users were confused by the mixed patterns, and discoverability suffered because actions were hidden in flags rather than visible in help output.

### Goals

1. **Consistency**: All commands follow the same pattern
2. **Discoverability**: All actions visible in `--help`
3. **Explicitness**: No implicit default behaviors
4. **Industry Alignment**: Match patterns from git, docker, kubectl, npm, aws CLI

## Design

### Command Pattern

All commands follow: `soothe <noun> <verb> [options]`

**Example**:
```bash
soothe thread list
soothe thread show abc123
soothe thread continue abc123 --daemon
```

### Key Principles

1. **No Default Actions**: Running `soothe thread` shows help, not a default action
2. **Explicit Verbs**: All operations require action verb (list, show, continue, etc.)
3. **Optional Positional Args**: Some actions accept optional positional args (e.g., `continue [THREAD_ID]`)
4. **Action-Specific Options**: Each action has its own option namespace

### Command Hierarchy

#### thread
- `soothe thread list` - List all threads
- `soothe thread show THREAD_ID` - Show thread details
- `soothe thread continue [THREAD_ID]` - Continue thread in TUI
- `soothe thread archive THREAD_ID` - Archive thread
- `soothe thread delete THREAD_ID` - Delete thread
- `soothe thread export THREAD_ID` - Export thread
- `soothe thread stats THREAD_ID` - Show statistics
- `soothe thread tag THREAD_ID TAGS...` - Add/remove tags

#### config
- `soothe config show` - Show configuration
- `soothe config init` - Initialize config
- `soothe config validate` - Validate config

#### agent
- `soothe agent list` - List agents
- `soothe agent status` - Show agent status

#### daemon (unchanged)
- `soothe daemon start` - Start daemon
- `soothe daemon stop` - Stop daemon
- `soothe daemon status` - Show daemon status
- `soothe daemon restart` - Restart daemon

#### autopilot
- `soothe autopilot run PROMPT` - Run autonomous task

## Implementation

### Phase 1: Code Changes

#### File: `src/soothe/ux/cli/main.py`

**Before** (flat pattern with flags):
```python
@app.command()
def thread(
    ctx: typer.Context,
    thread_id: str | None = None,
    list_threads: bool = False,
    continue_thread: bool = False,
    # ... many more flags
) -> None:
    # Dispatch logic with if/else blocks
    if list_threads:
        thread_list(...)
    elif continue_thread:
        thread_continue(...)
    # ... etc
```

**After** (nested subcommands):
```python
thread_app = typer.Typer(name="thread", help="Manage conversation threads")
add_help_alias(thread_app)
app.add_typer(thread_app)

@thread_app.command("list")
def _thread_list_cmd(
    config: str | None = None,
    status: str | None = None,
) -> None:
    """List all threads."""
    from soothe.ux.cli.commands.thread_cmd import thread_list
    thread_list(config=config, status=status)

@thread_app.command("continue")
def _thread_continue_cmd(
    thread_id: str | None = None,
    config: str | None = None,
    daemon: bool = False,
    new: bool = False,
) -> None:
    """Continue thread in TUI."""
    from soothe.ux.cli.commands.thread_cmd import thread_continue
    thread_continue(thread_id=thread_id, config=config, daemon=daemon, new=new)
```

**Changes**:
- Replace `@app.command()` with `typer.Typer()` for each command group
- Convert each action flag to a separate `@<app>.command("<action>")` function
- Remove dispatch logic
- Action-specific options move to their respective command functions
- Global options (like `--config`) appear in all commands

#### File: `src/soothe/ux/cli/commands/thread_cmd.py`

**Changes**: Update docstrings only

```python
def thread_list(...) -> None:
    """List all agent threads.

    Examples:
        soothe thread list
        soothe thread list --status active
    """
```

No structural changes needed - functions already properly separated.

#### Similar changes for:
- `src/soothe/ux/cli/commands/config_cmd.py` - Update docstrings
- `src/soothe/ux/cli/commands/status_cmd.py` - Update docstrings

### Phase 2: Documentation Updates

#### RFC-500: CLI Architecture

Update command table (lines 200-226) with nested structure.

#### User Documentation

1. **docs/wiki/cli-reference.md** - Complete rewrite
2. **docs/wiki/thread-management.md** - Update examples
3. **docs/wiki/getting-started.md** - Update examples
4. **docs/user_guide.md** - Update all CLI references
5. **README.md** - Update quickstart examples

### Phase 3: Testing

#### Unit Tests

Update test invocations:
```python
# Old
result = runner.invoke(app, ["thread", "-c", "abc123"])

# New
result = runner.invoke(app, ["thread", "continue", "abc123"])
```

#### Verification

Run `./scripts/verify_finally.sh` to ensure:
- Code formatting passes
- Linting has zero errors
- All 900+ tests pass

## Migration Guide

### For Users

| Old Command | New Command |
|-------------|-------------|
| `soothe thread` | `soothe thread list` |
| `soothe thread -c <id>` | `soothe thread continue <id>` |
| `soothe thread -d <id>` | `soothe thread delete <id>` |
| `soothe config -i` | `soothe config init` |
| `soothe agent --status` | `soothe agent status` |
| `soothe autopilot "task"` | `soothe autopilot run "task"` |

### For Developers

- No backward compatibility - clean break
- Update all CLI examples in documentation
- Update test cases to use new syntax

## Trade-offs

### Pros

- **Consistency**: All commands follow same pattern
- **Discoverability**: Help shows all actions
- **Extensibility**: Easy to add actions without flag conflicts
- **Industry Standard**: Matches git, docker, kubectl patterns

### Cons

- **More Verbose**: `soothe thread show ID` vs `soothe thread ID`
- **Breaking Change**: Users must update workflows
- **Reverts IG-050**: Undoes recent work

## Rationale

**Why revert IG-050**:

IG-050 created inconsistency by flattening most commands while keeping daemon nested. This violated the principle of least surprise and made the CLI harder to learn. The nested pattern is more explicit, more discoverable, and aligns with industry standards.

**Why no backward compatibility**:

1. Early stage project with small user base
2. Simpler implementation without deprecated paths
3. Clear, one-time migration for users
4. Higher code quality without compatibility shims

## Related Documents

- [RFC-500: CLI TUI Architecture Design](../specs/RFC-500-cli-tui-architecture.md)
- [IG-050: CLI Subcommand Flattening](./050-cli-subcommand-flattening.md) (reverted by this guide)
- [User Guide](../user_guide.md)
- [CLI Reference](../wiki/cli-reference.md)

## Checklist

- [ ] Update `src/soothe/ux/cli/main.py` with nested structure
- [ ] Update docstrings in `thread_cmd.py`
- [ ] Update docstrings in `config_cmd.py`
- [ ] Update docstrings in `status_cmd.py`
- [ ] Update RFC-500 command table
- [ ] Rewrite `docs/wiki/cli-reference.md`
- [ ] Update `docs/wiki/thread-management.md`
- [ ] Update `docs/wiki/getting-started.md`
- [ ] Update `docs/user_guide.md`
- [ ] Update `README.md`
- [ ] Update unit tests
- [ ] Run `./scripts/verify_finally.sh`
- [ ] Manual testing of all commands

## Notes

This guide documents a significant CLI restructure. All code changes should follow the plan file at `/Users/chenxm/.claude/plans/replicated-imagining-beacon.md` for detailed implementation steps.