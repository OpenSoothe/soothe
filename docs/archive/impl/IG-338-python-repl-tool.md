# IG-338: Replace RunPythonTool with langchain_experimental PythonREPLTool

## Goal

Remove bespoke `RunPythonTool` / `PythonSessionManager` and use `langchain_experimental.tools.python.PythonREPLTool` with `PythonREPL`, preserving tool name `run_python` and parameter `code`, and documenting REPL persistence semantics.

## Scope

- Add `langchain-experimental` to daemon core dependencies.
- Implement `RunPythonREPLTool(PythonREPLTool)` with Soothe naming and args schema.
- Remove `python_session_manager.py` and session-manager integration tests that only covered the old stack.

## Status

Completed.
