# Soothe CLI Enhancement Plan

## Executive Summary

The Soothe CLI is already well-structured using **Typer** for command definition and follows Unix conventions. This plan documents the current state, identifies enhancements, and provides a structured approach for future CLI development.

---

## 1. Current CLI Structure

### 1.1 Entry Point
- **Location**: `/src/soothe/cli/main.py`
- **Framework**: Typer (with Rich for rich terminal output)
- **Command**: `soothe`

### 1.2 Existing Commands

| Command | Description | Status |
|---------|-------------|--------|
| `soothe run [PROMPT]` | Run agent interactively or headless | ✓ Complete |
| `soothe list-subagents` | List available subagents | ✓ Complete |
| `soothe config` | Display configuration | ✓ Complete |
| `soothe init` | Initialize ~/.soothe directory | ✓ Complete |
| `soothe server start|stop|status` | Daemon management | ✓ Complete |
| `soothe attach` | Attach to running daemon | ✓ Complete |
| `soothe thread list` | List all threads | ✓ Complete |
| `soothe thread resume <ID>` | Resume a thread | ✓ Complete |
| `soothe thread archive <ID>` | Archive a thread | ✓ Complete |
| `soothe thread delete <ID>` | Delete a thread | ✓ Complete |
| `soothe thread export <ID>` | Export thread to file | ✓ Complete |
| `soothe thread inspect <ID>` | Inspect thread details | ✓ Complete |

### 1.3 Directory Structure

```
/src/soothe/cli/
├── __init__.py
├── main.py           # Typer app definition, CLI entry point
├── commands.py       # Slash commands, subagent routing helpers
├── runner.py         # SootheRunner class for agent execution
├── session.py        # Session logging utilities
├── tui.py            # Legacy TUI runner (fallback)
├── tui_app.py        # Textual-based TUI application
├── daemon.py         # Background daemon management
```

---

## 2. Feature Gap Analysis

### 2.1 Missing Features (Requested in Task)

All requested features are already implemented:

| Requested Feature | Implementation | File Location |
|------------------|----------------|---------------|
| Run the agent | `soothe run` + `soothe server` | main.py:119-149 |
| List subagents | `soothe list-subagents` | main.py:27-71 |
| Check config | `soothe config` | main.py:255-330 |

### 2.2 Potential Enhancements

#### High Priority
1. **Interactive Prompt Wizard** - Guided first-run setup
2. **Config Validation** - `soothe config validate` to check API keys and settings
3. **Subagent Control** - Enable/disable subagents at runtime
4. **Thread Search** - `soothe thread search <query>` - find threads by content
5. **Stats Dashboard** - `soothe stats` showing usage metrics

#### Medium Priority
6. **Export All Threads** - Batch export functionality
7. **Configuration Templates** - Pre-built configs for common use cases
8. **Quick Commands** - Aliases like `soothe s` → `soothe submit`
9. **Auto-completion Updates** - Better shell completion support
10. **Multi-config Support** - `soothe --env production run`

#### Low Priority
11. **Plugin Discovery** - `soothe plugins list`
12. **Health Check** - `soothe health` for system diagnostics
13. **Log Viewer** - `soothe logs [thread_id]`

---

## 3. Proposed Architecture for New Commands

### 3.1 Command Organization Strategy

Use **sub-apps** for related commands (pattern already used for `server` and `thread`):

```python
# Example structure
app = typer.Typer(name="soothe")

# Core commands (already exist)
@app.command()
def run(...)

@app.command()
def config(...)

@app.command()
def list_subagents(...)

# New sub-apps to consider
setup_app = typer.Typer(name="setup", help="Interactive setup wizards")
stats_app = typer.Typer(name="stats", help="Usage statistics")
control_app = typer.Typer(name="control", help="Runtime control")
```

### 3.2 Command Design Patterns

Follow existing patterns for consistency:

1. **Configuration loading**: Use `_load_config()` helper
2. **Error handling**: Try/except with keyboard interrupt handling
3. **Output formatting**: Use Rich tables for tabular data
4. **Async operations**: Wrap in `asyncio.run()` for threading

---

## 4. Implementation Roadmap

### Phase 1: Configuration Enhancements (Week 1-2)
- [ ] `soothe config validate` - Validate configuration
- [ ] `soothe config show-profile` - View named config profiles
- [ ] `soothe config apply <profile>` - Apply config profile

**Tasks:**
1. Add config validation logic to config.py
2. Create `validate_config()` function in main.py
3. Add progress indicators using Rich
4. Add unit tests for config validation

### Phase 2: Subagent Management (Week 2-3)
- [ ] `soothe subagent enable <name>` - Enable a subagent
- [ ] `soothe subagent disable <name>` - Disable a subagent
- [ ] `soothe subagent set-model <name> <model>` - Set custom model

**Tasks:**
1. Create `subagents/` sub-app in main.py
2. Implement enable/disable logic via config modification
3. Add confirmation prompts for destructive actions
4. Write tests for subagent management

### Phase 3: Thread Management Expansion (Week 3-4)
- [ ] `soothe thread search <query>` - Search thread contents
- [ ] `soothe thread export-all` - Export all active threads
- [ ] `soothe thread cleanup` - Remove old archived threads

**Tasks:**
1. Implement text search in SessionLogger
2. Add pagination for large result sets
3. Create batch export utility
4. Test with various thread volumes

### Phase 4: Statistics and Reporting (Week 4-5)
- [ ] `soothe stats summary` - Overall usage statistics
- [ ] `soothe stats per-thread` - Stats per thread
- [ ] `soothe stats export` - Export stats to JSON

**Tasks:**
1. Query SessionLogger for aggregated data
2. Calculate tokens, time, thread counts
3. Format as Rich table
4. Add JSON export option

---

## 5. Technical Considerations

### 5.1 Dependencies (Already Present)
- ✅ Typer (CLI framework)
- ✅ Rich (terminal UI)
- ✅ PyYAML (config parsing)
- ✅ Pydantic (config validation)
- ✅ asyncio (async operations)

### 5.2 Code Quality Standards
- Follow existing type hints pattern (`Annotated[...]`)
- Use docstrings with Args/Returns sections
- Keep functions under 50 lines where possible
- Wrap external calls in try/except blocks
- Use `sys.exit()` for error termination

### 5.3 Testing Requirements
- Unit tests for each new command
- Integration tests for CLI flow
- Mock configuration for test isolation
- Coverage target: >80% for new code

---

## 6. Documentation Checklist

For each new command:
- [ ] Add to README.md CLI section
- [ ] Include examples in docstrings
- [ ] Update help text (`--help` output)
- [ ] Document exit codes
- [ ] Add troubleshooting notes if needed

---

## 7. Immediate Next Steps

Since the three core requested features (**run**, **list-subagents**, **config**) are already fully implemented, no immediate implementation work is required.

### Recommended Actions:
1. **Verify completeness**: Confirm all three features work as documented
2. **Review user experience**: Test CLI from fresh install perspective
3. **Gather feature requests**: Identify what users actually need next
4. **Consider Phase 1**: Start with config validation if desired

---

## Appendix: Key Code References

### Main CLI Definition
```python
# /src/soothe/cli/main.py:13-17
app = typer.Typer(
    name="soothe",
    help="Multi-agent harness built on deepagents and langchain/langgraph.",
    add_completion=False,
)
```

### Config Loading Helper
```python
# /src/soothe/cli/main.py:74-111
def _load_config(config_path: str | None) -> SootheConfig:
    """Load config from file path or defaults."""
    # ...implementation
```

### Subagent Display Names
```python
# /src/soothe/cli/commands.py:23-31
SUBAGENT_DISPLAY_NAMES: dict[str, str] = {
    "planner": "Planner",
    "scout": "Scout",
    "research": "Research",
    "browser": "Browser",
    "claude": "Claude",
}
```

---

*Document created: CLI planning phase*
*Status: Review pending*
