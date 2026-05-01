# IG-336: Replace RunCommandTool with langchain_community ShellTool

## Goal

Remove custom `RunCommandTool` and use `langchain_community.tools.ShellTool` as the base for synchronous shell execution (`run_command`), preserving Soothe behavior: operation security, workspace resolution (`ToolRuntime`), timeouts, and output limits.

## Scope

- Subclass `ShellTool` (`RunCommandShellTool`) with name `run_command`, custom args schema (`command`, optional `timeout`), injected `runtime`, and subprocess execution (no pexpect persistent shell).
- Refactor `run_background` and `kill_process` to use `subprocess` / `os.kill` (they previously depended on the pexpect shell).
- Remove `packages/soothe/src/soothe/toolkits/_internal/shell.py` if obsolete; update tests.

## Status

Completed. `RunCommandShellTool` subclasses `langchain_community.tools.ShellTool`; persistent pexpect shell removed; `run_background` / `kill_process` use subprocess / `os.kill`.
