# Migration Guide: Soothe v0.3.0 (CLI-Daemon Split)

**Important**: Soothe v0.3.0 introduces a major architectural change - the monolithic package has been split into three independent packages.

## Quick Start

```bash
# Uninstall old package
pip uninstall soothe

# Install new packages
pip install soothe-cli soothe-daemon[all]

# Update commands
soothe-daemon start    # (was: soothe daemon start)
soothe-daemon doctor   # (was: soothe doctor)
soothe -p "query"      # (unchanged)
```

## What Changed?

### Package Split

| Old Package | New Packages |
|-------------|--------------|
| soothe (v0.2.x) | soothe-sdk (v0.2.0) |
| | soothe-cli (v0.1.0) |
| | soothe-daemon (v0.3.0) |

### Command Changes

**Moved to `soothe-daemon`**:
- `soothe daemon start` → `soothe-daemon start`
- `soothe daemon stop` → `soothe-daemon stop`
- `soothe daemon status` → `soothe-daemon status`
- `soothe daemon restart` → `soothe-daemon restart`
- `soothe doctor` → `soothe-daemon doctor`

**Unchanged (in `soothe-cli`)**:
- `soothe` (default TUI/headless)
- `soothe thread list/continue/show`
- `soothe config show/init`
- `soothe agent list/status`
- `soothe autopilot run`

### Configuration Changes

**New**: Create `~/.soothe/cli_config.yml` for CLI-specific settings.

**Unchanged**: `~/.soothe/config.yml` works for daemon.

## Full Migration Guide

See [docs/migration-guide-v0.3.md](docs/migration-guide-v0.3.md) for complete details.

## Architecture Documentation

See [docs/cli-daemon-architecture.md](docs/cli-daemon-architecture.md) for architecture overview.

## Support

- GitHub Issues: https://github.com/caesar0301/soothe/issues
- Implementation Guide: docs/impl/IG-173-cli-daemon-split-refactoring.md
