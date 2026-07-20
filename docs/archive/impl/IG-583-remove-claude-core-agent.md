# IG-583: Remove Claude Code Core Agent

**Created**: 2026-07-12  
**Status**: Implemented  
**Related**: [IG-202](archive/IG-202-claude-thread-session-alignment.md), [IG-457](archive/IG-457-promote-browser-use-claude-subagents.md)

---

## Summary

Removed the alternate `ClaudeCoreAgent` backend (`core_agent_backend: claude`) and the `claude-agent-sdk` dependency. Soothe now uses LangGraph/deepagents exclusively for CoreAgent execution. Embeddings and chat still use the `anthropic` provider via LangChain when configured in router profiles.

---

## Removed

- `ClaudeCoreAgent` implementation (`_claude_agent.py`, `_claude_session.py`, `_claude_display.py`)
- Config: `core_agent_backend`, `claude_*` agent fields, `always_claude` planner routing
- `ThreadMetadata.claude_sessions` and executor/daemon session bridge
- `soothe[claude]` optional extra and `claude-agent-sdk` dependency
- `soothed warmup` was already removed in IG-582 (unrelated)

---

## Migration

Legacy YAML keys are stripped at load time (`core_agent_backend`, `claude_*`, `always_claude` → `auto`, `claude_sessions` in thread metadata).

---

## Verification

```bash
./scripts/verify_finally.sh
```
