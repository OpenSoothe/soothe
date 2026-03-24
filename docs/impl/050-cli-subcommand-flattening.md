# IG-050: CLI Subcommand Flattening

**Status**: Approved
**Created**: 2026-03-24
**Author**: Claude Code

## Abstract

Refactor Soothe CLI commands to follow a flat pattern `soothe <subcommand> <options>` instead of nested subcommands like `soothe thread list/continue`. This simplifies the command interface and improves discoverability.

## Motivation

### Current Problems

1. **Nested Subcommands**: Commands like `soothe thread list`, `soothe daemon start` require users to remember two-level command structures
2. **Inconsistent with Unix Conventions**: Most CLI tools use flags for actions, not nested subcommands
3. **Verbose**: `soothe thread continue <id>` is longer than `soothe thread -c <id>`
4. **Poor Discoverability**: Users must know the nested structure to find commands

### Goals

- Single-level subcommands with action flags
- Short and long form options for common actions
- Backward compatibility maintained where possible
- Clear and consistent documentation

## Design

### Command Transformation

#### Thread Commands

| Old Pattern | New Pattern |
|-------------|-------------|
| `soothe thread list` | `soothe thread -l` or `soothe thread --list` |
| `soothe thread show <id>` | `soothe thread <id>` or `soothe thread --show <id>` |
| `soothe thread continue <id>` | `soothe thread -c <id>` or `soothe thread --continue <id>` |
| `soothe thread archive <id>` | `soothe thread -a <id>` or `soothe thread --archive <id>` |
| `soothe thread delete <id>` | `soothe thread -d <id>` or `soothe thread --delete <id>` |
| `soothe thread export <id>` | `soothe thread -e <id>` or `soothe thread --export <id>` |
| `soothe thread stats <id>` | `soothe thread --stats <id>` |
| `soothe thread tag <id> <tags...>` | `soothe thread --tag <id> <tags...>` |

**Default Behavior**: `soothe thread <id>` shows thread details (same as old `thread show`).

#### Daemon Commands

**Note**: Daemon commands remain as nested subcommands for consistency with common daemon CLI patterns.

| Command | Description |
|---------|-------------|
| `soothe daemon start` | Start daemon in background |
| `soothe daemon start --foreground` | Start daemon in foreground |
| `soothe daemon stop` | Stop daemon |
| `soothe daemon status` | Show daemon status |
| `soothe daemon restart` | Restart daemon |

#### Config Commands

| Old Pattern | New Pattern |
|-------------|-------------|
| `soothe config show` | `soothe config -s` or `soothe config --show` |
| `soothe config init` | `soothe config -i` or `soothe config --init` |
| `soothe config validate` | `soothe config --validate` |

**Default Behavior**: `soothe config` shows current config (same as old `config show`).

#### Agent Commands

| Old Pattern | New Pattern |
|-------------|-------------|
| `soothe agent list` | `soothe agent -l` or `soothe agent --list` |
| `soothe agent status` | `soothe agent --status` |

**Default Behavior**: `soothe agent` lists agents (same as old `agent list`).

### Short Option Summary

| Command | Short Option | Long Option | Description |
|---------|--------------|-------------|-------------|
| thread | `-l` | `--list` | List threads |
| thread | `-s` | `--show` | Show thread (default action) |
| thread | `-c` | `--continue` | Continue thread in TUI |
| thread | `-a` | `--archive` | Archive thread |
| thread | `-d` | `--delete` | Delete thread |
| thread | `-e` | `--export` | Export thread |
| thread | | `--stats` | Show thread stats |
| thread | | `--tag` | Tag thread |
| daemon | | `start` | Start daemon (nested subcommand) |
| daemon | | `stop` | Stop daemon (nested subcommand) |
| daemon | | `status` | Show daemon status (nested subcommand) |
| daemon | | `restart` | Restart daemon (nested subcommand) |
| config | `-s` | `--show` | Show config (default) |
| config | `-i` | `--init` | Initialize config |
| config | | `--validate` | Validate config |
| agent | `-l` | `--list` | List agents (default) |
| agent | | `--status` | Show agent status |

## Implementation

### Files to Modify

1. **`src/soothe/ux/cli/main.py`** - Refactor command registration from nested Typer apps to single commands with options
2. **`src/soothe/ux/cli/commands/thread_cmd.py`** - Update function signatures for new option pattern
3. **`src/soothe/ux/cli/commands/daemon_cmd.py`** - Update function signatures for new option pattern
4. **`src/soothe/ux/cli/commands/config_cmd.py`** - Update function signatures for new option pattern
5. **`src/soothe/ux/cli/commands/status_cmd.py`** - Update function signatures for new option pattern

### Documentation Updates

1. **`docs/wiki/cli-reference.md`** - Update all command examples
2. **`docs/wiki/thread-management.md`** - Update thread command examples
3. **`docs/wiki/daemon-management.md`** - Update daemon command examples
4. **`docs/wiki/getting-started.md`** - Update command examples
5. **`docs/specs/RFC-0003.md`** - Update CLI command table
6. **`docs/user_guide.md`** - Update command examples

### Implementation Approach

1. Convert nested Typer apps to single commands with action flags
2. Make positional arguments work as the primary operand (e.g., thread_id)
3. Use mutually exclusive groups where needed (e.g., can't do --list and --show together)
4. Provide sensible defaults when no action flag is specified
5. Update all documentation to reflect new patterns

### Backward Compatibility

Since this is a breaking change, we will:
- Update all documentation to show new patterns
- The new pattern is more intuitive, so migration should be straightforward
- Users will need to update their scripts/muscle memory

## Testing

### Manual Testing Commands

```bash
# Thread commands
soothe thread -l
soothe thread -l -s active
soothe thread abc123
soothe thread -c abc123
soothe thread -c --daemon abc123
soothe thread -a abc123
soothe thread -d abc123
soothe thread -e abc123 -o thread.json
soothe thread --stats abc123
soothe thread --tag abc123 research

# Daemon commands (nested subcommands - unchanged)
soothe daemon start
soothe daemon stop
soothe daemon status
soothe daemon restart
soothe daemon start --foreground

# Config commands
soothe config
soothe config -i
soothe config --validate

# Agent commands
soothe agent
soothe agent --status
```

## References

- Original spec: `docs/specs/RFC-0003.md`
- CLI Reference: `docs/wiki/cli-reference.md`
- Current implementation: `src/soothe/ux/cli/main.py`
