# IG-020: Detached Daemon Autonomous Capability

## Objective

Enable reliable autonomous background execution when users detach from the TUI, while keeping autonomous mode explicit-by-default and validating `task-download-skills.md` as a capability test using existing Soothe tools/subagents.

## Scope

1. Externalize TUI daemon bootstrap so detached sessions keep running.
2. Expose autonomous runtime controls in configuration and propagate through daemon/TUI.
3. Add an explicit TUI autonomous command surface (`/auto ...`).
4. Add tests and docs for detach persistence and autonomous option propagation.

## Non-Goals

- No built-in SkillHub downloader tool or source-specific hardcoded crawler.
- No changes to Skillify behavior or warehouse path defaults.
- No new protocol additions.

## Design

### 1) Detached execution model

- `run_textual_tui()` ensures a daemon exists as an external process.
- TUI detach only closes the client connection.
- Daemon lifecycle is no longer tied to TUI process lifetime.

### 2) Autonomous option flow

- New config flag: `autonomous_enabled_by_default: false`.
- TUI normal input inherits this default.
- `/auto <prompt>` and `/auto <max_iterations> <prompt>` override to autonomous mode for a specific request.
- Daemon IPC input messages carry:
  - `autonomous: bool`
  - `max_iterations: int | None`
- Daemon forwards these to `SootheRunner.astream(...)`.

### 3) Capability-test workflow (task-download-skills)

Use existing capabilities only:
- Discovery: `wizsearch_search` and browser subagent.
- Crawl: `wizsearch_crawl_page` with browser fallback.
- Save: existing filesystem/file-edit tools into `downloaded_skills/<source>/<skill>/`.
- Decomposition: existing `manage_goals` tool in autonomous loop.

## Files

- `src/soothe/cli/tui_app.py`
- `src/soothe/cli/daemon.py`
- `src/soothe/cli/commands.py`
- `src/soothe/config.py`
- `config/config.yml`
- `docs/user_guide.md`
- `tests/unit_tests/test_cli_daemon.py`
- `tests/unit_tests/test_cli_tui_app.py`
- `tests/unit_tests/test_cli_commands_autonomous.py`
- `tests/unit_tests/test_config.py`

## Validation

- Unit tests verify:
  - daemon propagation of autonomous options,
  - client payload encoding for autonomous options,
  - external daemon startup behavior from TUI path,
  - autonomous slash command parsing.
- Manual verification:
  1. Start TUI (`soothe run`)
  2. Run `/auto 20 <task>`
  3. Detach (`/detach`)
  4. Reattach (`soothe attach`) and confirm progress continues.
