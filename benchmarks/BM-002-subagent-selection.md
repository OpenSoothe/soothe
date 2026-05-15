# BM-002: Subagent Selection and Routing Benchmark

> **Purpose**: Verify that subagent routing works correctly for core slash prefixes and that queries without a prefix stay on the main agent.
>
> **Last Updated**: 2026-05-15
>
> **Status**: Active

---

## Overview

This benchmark validates:

1. **Explicit routing** via `/research` and `/explore` slash commands
2. **Inline routing** where the slash command appears in the middle of the query
3. **Case-insensitive routing** (`/Research`, `/Explore`, etc.)
4. **No-subagent passthrough** — queries that should stay in the main agent are not incorrectly routed
5. **Multi-command first-wins** — when multiple slash commands appear, only the first is used

### Core subagents under test

| Subagent | Slash command | Purpose |
|----------|---------------|---------|
| research | `/research` | Deep multi-source iterative research |
| explore | `/explore` | Readonly repository search |

Additional delegated agents are not covered here; install and benchmark them from the **`soothe-community`** repository.

---

## Verification Approach

Each test case can be verified by **two complementary methods**:

### Method A: Daemon Log Check
```bash
grep -E "Quick path: routing directly to subagent" ~/.soothe/logs/soothe.log | tail -5
# Expect: "Quick path: routing directly to subagent '<name>'"
```

### Method B: CLI Output Content
Check that the agent's response reflects the routed delegate’s behavior.

---

## Test Cases

### TC-001: Explicit `/research` Slash Command (Prefix)

**Query**: `"/research what are the main differences between PostgreSQL and SQLite"`

**Expected Behavior**:
- `parse_subagent_from_input()` extracts `subagent="research"`, cleaned text without the slash token
- Runner quick-paths to the research subagent when enabled in config

**Verification Conditions**:
- [ ] Daemon log contains: `Quick path: routing directly to subagent 'research'`
- [ ] Response is a structured research synthesis
- [ ] Step completes in < 120 seconds

---

### TC-002: Explicit `/explore` Slash Command (Prefix)

**Query**: `"/explore locate the module that registers HTTP routes"`

**Expected Behavior**:
- `parse_subagent_from_input()` extracts `subagent="explore"` with cleaned text
- Runner quick-paths to the explore subagent when enabled in config

**Verification Conditions**:
- [ ] Daemon log contains: `Quick path: routing directly to subagent 'explore'`
- [ ] Response reflects filesystem search activity
- [ ] Step completes in < 120 seconds

---

### TC-003: Inline Slash Command (Embedded in Query)

**Query**: `"Can you /research the history of Python programming language and give me a summary"`

**Expected Behavior**:
- `parse_subagent_from_input()` finds `/research` inline
- Runner quick-paths to research subagent

**Verification Conditions**:
- [ ] Daemon log contains: `Quick path: routing directly to subagent 'research'`
- [ ] The `/research` token does not appear in the cleaned query sent to the delegate
- [ ] Step completes in < 120 seconds

---

### TC-004: Case-Insensitive Slash Command

**Query**: `"/Explore map the tests directory for asyncio usage"`

**Expected Behavior**:
- Case-insensitive match extracts `subagent="explore"`

**Verification Conditions**:
- [ ] Daemon log contains: `Quick path: routing directly to subagent 'explore'`
- [ ] Step completes in < 120 seconds

---

### TC-005: No Subagent — Filesystem-Only Query

**Query**: `"read the first 5 lines of pyproject.toml"`

**Expected Behavior**:
- No slash command → `parse_subagent_from_input()` returns `(None, query)`
- Main agent handles the query

**Verification Conditions**:
- [ ] Daemon log does NOT contain: `Quick path: routing directly to subagent`
- [ ] Response contains actual content from `pyproject.toml`

---

### TC-006: Multi-Subagent Command — First Match Wins

**Query**: `"/research summarize SQLite WAL mode and /explore find mentions in docs/"`

**Expected Behavior**:
- First slash token wins (`research`); later slash remains in cleaned text or is ignored per parser rules

**Verification Conditions**:
- [ ] Only one subagent quick-path activation occurs for the first token
- [ ] Daemon behavior matches the current `parse_subagent_from_input` contract

---

## Execution Instructions

### Prerequisites

```bash
# Ensure daemon is running
uv run soothed status

# If not running, start it
uv run soothed start --config config/config.dev.yml
```

### Run Command Format

```bash
uv run soothe --no-tui -p "/research what are the main differences between PostgreSQL and SQLite"
uv run soothe --no-tui -p "/explore locate the module that registers HTTP routes"
```

---

## Unit Test Verification (`parse_subagent_from_input`)

```python
from soothe_cli.shared.commands.subagent_routing import parse_subagent_from_input

assert parse_subagent_from_input("/research history of Python") == ("research", "history of Python")
assert parse_subagent_from_input("/explore map src") == ("explore", "map src")
subagent, cleaned = parse_subagent_from_input("Can you /research the history of Python")
assert subagent == "research"
assert "/research" not in cleaned
assert parse_subagent_from_input("/Explore map tests")[0] == "explore"
```

---

## Related Files

- `packages/soothe-cli/src/soothe_cli/shared/commands/subagent_routing.py` — `parse_subagent_from_input()`
- `packages/soothe/src/soothe/core/runner/__init__.py` — quick path for subagent routing
- `packages/soothe/src/soothe/core/resolver/_resolver_tools.py` — `resolve_subagents()`
- `docs/wiki/subagents.md` — end-user overview of core subagents
