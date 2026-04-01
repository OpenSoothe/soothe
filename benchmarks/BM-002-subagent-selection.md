# BM-002: Subagent Selection and Routing Benchmark

> **Purpose**: Verify that subagent routing works correctly — both explicit slash-command activation and non-subagent passthrough for queries that should stay in the main agent.
>
> **Last Updated**: 2026-04-01
>
> **Status**: Active

---

## Overview

This benchmark validates:

1. **Explicit routing** via `/subagentname` slash commands routes correctly to the three tested subagents
2. **Inline routing** where the slash command appears in the middle of the query
3. **Case-insensitive routing** (`/BROWSER`, `/Research`, etc.)
4. **No-subagent passthrough** — queries that should stay in the main agent are not incorrectly routed to a subagent
5. **Multi-command first-wins** — when multiple slash commands appear, only the first is used

### Tested Subagents

| Subagent   | Slash Command  | Purpose |
|------------|---------------|---------|
| browser    | `/browser`    | Interactive web browsing, form filling, JS-heavy sites |
| claude     | `/claude`     | Complex reasoning with Claude model directly |
| research   | `/research`   | Deep multi-source iterative research |

---

## Verification Approach

Each test case can be verified by **two complementary methods**:

### Method A: Daemon Log Check
```bash
grep -E "Quick path: routing directly to subagent" ~/.soothe/logs/soothe.log | tail -5
# Expect: "Quick path: routing directly to subagent '<name>'"
```

### Method B: CLI Output Content
Check that the agent's response reflects the subagent's characteristic behavior/format.

---

## Test Cases

### TC-001: Explicit `/browser` Slash Command (Prefix)

**Query**: `"/browser go to https://example.com and tell me the page title"`

**Expected Behavior**:
- `parse_subagent_from_input()` extracts `subagent="browser"`, `text="go to https://example.com and tell me the page title"`
- Runner takes "quick path" and calls `create_browser_subagent()`
- Response is from the browser subagent (may fail gracefully if Chrome not available, but routing must happen)

**Verification Conditions**:
- [ ] Daemon log contains: `Quick path: routing directly to subagent 'browser'`
- [ ] Response does NOT contain main-agent tool calls (`read_file`, `run_command`)
- [ ] If browser unavailable, response mentions browser/navigation, not a fallback tool
- [ ] Step completes in < 60 seconds

**Success Criteria**:
```
Log: "Quick path: routing directly to subagent 'browser'"
Response: references navigation / browser / page content (or graceful browser unavailability message)
```

---

### TC-002: Explicit `/research` Slash Command (Prefix)

**Query**: `"/research what are the main differences between PostgreSQL and SQLite"`

**Expected Behavior**:
- `parse_subagent_from_input()` extracts `subagent="research"`, `text="what are the main differences between PostgreSQL and SQLite"`
- Runner quick-paths to `create_research_subagent()`
- Response is a structured research synthesis

**Verification Conditions**:
- [ ] Daemon log contains: `Quick path: routing directly to subagent 'research'`
- [ ] Response contains structured research output (sources, synthesis, or multi-angle analysis)
- [ ] Response does NOT start with a plan using `read_file` or `run_command` for a web topic
- [ ] Step completes in < 120 seconds

**Success Criteria**:
```
Log: "Quick path: routing directly to subagent 'research'"
Response: contains comparison of PostgreSQL vs SQLite with sourced or synthesized information
```

---

### TC-003: Explicit `/claude` Slash Command (Prefix)

**Query**: `"/claude explain the difference between supervised and unsupervised learning in one paragraph"`

**Expected Behavior**:
- `parse_subagent_from_input()` extracts `subagent="claude"`, `text="explain the difference between supervised and unsupervised learning in one paragraph"`
- Runner quick-paths to `create_claude_subagent()`
- Response is a direct answer from Claude subagent

**Verification Conditions**:
- [ ] Daemon log contains: `Quick path: routing directly to subagent 'claude'`
- [ ] Response is a cohesive paragraph on supervised vs unsupervised learning
- [ ] Response does NOT invoke tools like `web_search` for this factual question
- [ ] Step completes in < 60 seconds

**Success Criteria**:
```
Log: "Quick path: routing directly to subagent 'claude'"
Response: a paragraph mentioning labeled/unlabeled data or training paradigms
```

---

### TC-004: Inline Slash Command (Embedded in Query)

**Query**: `"Can you /research the history of Python programming language and give me a summary"`

**Expected Behavior**:
- `parse_subagent_from_input()` finds `/research` inline, extracts `subagent="research"`
- Cleaned text becomes: `"Can you the history of Python programming language and give me a summary"`
- Runner quick-paths to research subagent

**Verification Conditions**:
- [ ] Daemon log contains: `Quick path: routing directly to subagent 'research'`
- [ ] Response is a research synthesis about Python history, NOT main-agent response
- [ ] The word `/research` does NOT appear in the cleaned query sent to the agent
- [ ] Step completes in < 120 seconds

**Success Criteria**:
```
Log: "Quick path: routing directly to subagent 'research'"
Response: structured information about Python history (Guido van Rossum, 1991, etc.)
```

---

### TC-005: Case-Insensitive Slash Command

**Query**: `"/BROWSER navigate to https://httpbin.org/json and show the JSON response"`

**Expected Behavior**:
- `parse_subagent_from_input()` does case-insensitive match, extracts `subagent="browser"`
- Routing proceeds identically to TC-001

**Verification Conditions**:
- [ ] Daemon log contains: `Quick path: routing directly to subagent 'browser'`
- [ ] Response reflects browser activity (or graceful unavailability)
- [ ] Case-insensitivity does NOT cause a routing failure or main-agent fallback
- [ ] Step completes in < 60 seconds

**Success Criteria**:
```
Log: "Quick path: routing directly to subagent 'browser'"
Behavior: identical to TC-001 (routing works regardless of case)
```

---

### TC-006: No Subagent — Filesystem-Only Query

**Query**: `"read the first 5 lines of pyproject.toml"`

**Expected Behavior**:
- No slash command in query → `parse_subagent_from_input()` returns `(None, query)`
- Main agent handles query using `read_file` tool
- No subagent routing occurs

**Verification Conditions**:
- [ ] Daemon log does NOT contain: `Quick path: routing directly to subagent`
- [ ] Response contains actual content from `pyproject.toml`
- [ ] `read_file` or equivalent tool was used (not browser, research, or task dispatch)
- [ ] Step completes in < 30 seconds

**Success Criteria**:
```
Log: NO "Quick path" entry
Response: first 5 lines of pyproject.toml (e.g., [build-system], requires = [...])
Tool used: read_file (NOT task/subagent dispatch)
```

---

### TC-007: No Subagent — Simple Local Analysis Query

**Query**: `"list all Python files in the src/soothe/tools/ directory"`

**Expected Behavior**:
- No slash command → main agent handles using `list_files` or `run_command` (`find` / `ls`)
- No subagent routing occurs

**Verification Conditions**:
- [ ] Daemon log does NOT contain: `Quick path: routing directly to subagent`
- [ ] Response lists `.py` files from `src/soothe/tools/`
- [ ] Files listed are actual project files (not root filesystem)
- [ ] Step completes in < 30 seconds

**Success Criteria**:
```
Log: NO "Quick path" entry
Response: list includes implementation.py, __init__.py files under src/soothe/tools/
Tool used: list_files or run_command (NOT subagent dispatch)
```

---

### TC-008: Multi-Subagent Command — First Match Wins

**Query**: `"/browser open https://example.com and /research its history"`

**Expected Behavior**:
- `parse_subagent_from_input()` finds both `/browser` (index 0) and `/research` (later)
- First match wins: `subagent="browser"`
- Cleaned text: `"open https://example.com and /research its history"` (or `/research` stripped from cleaned text)
- Runner quick-paths to browser subagent, NOT research

**Verification Conditions**:
- [ ] Daemon log contains: `Quick path: routing directly to subagent 'browser'`
- [ ] Daemon log does NOT contain: `routing directly to subagent 'research'`
- [ ] Only ONE subagent is invoked
- [ ] Step completes in < 60 seconds

**Success Criteria**:
```
Log: "Quick path: routing directly to subagent 'browser'"  (first wins)
Log: NO entry for research subagent routing
```

---

---

## Execution Instructions

### Prerequisites

```bash
# Ensure daemon is running
uv run soothe daemon status

# If not running, start it
uv run soothe daemon start --config config.dev.yml

# Tail the log for verification during run
tail -f ~/.soothe/logs/soothe.log | grep -E "(Quick path|routing)" &
```

### Run Command Format

```bash
# Use the headless runner for each test
uv run soothe --no-tui -p "<query>"

# For slash commands, quote the full prompt including the slash
uv run soothe --no-tui -p "/browser go to https://example.com and tell me the page title"
```

### Run All Test Cases

```bash
# TC-001: browser explicit
uv run soothe --no-tui -p "/browser go to https://example.com and tell me the page title"

# TC-002: research explicit
uv run soothe --no-tui -p "/research what are the main differences between PostgreSQL and SQLite"

# TC-003: claude explicit
uv run soothe --no-tui -p "/claude explain the difference between supervised and unsupervised learning in one paragraph"

# TC-004: inline command
uv run soothe --no-tui -p "Can you /research the history of Python programming language and give me a summary"

# TC-005: case-insensitive
uv run soothe --no-tui -p "/BROWSER navigate to https://httpbin.org/json and show the JSON response"

# TC-006: no subagent (filesystem)
uv run soothe --no-tui -p "read the first 5 lines of pyproject.toml"

# TC-007: no subagent (local analysis)
uv run soothe --no-tui -p "list all Python files in the src/soothe/tools/ directory"

# TC-008: multi-command first-wins
uv run soothe --no-tui -p "/browser open https://example.com and /research its history"
```

---

## Log Verification Snippets

```bash
# Check routing decisions after running
grep -E "(Quick path|routing directly)" ~/.soothe/logs/soothe.log | tail -20

# Check for unexpected subagent activations
grep "routing directly to subagent" ~/.soothe/logs/soothe.log | tail -20
```

---

## Unit Test Verification (parse_subagent_from_input)

The core routing logic can be verified directly without running the full daemon:

```python
from soothe.ux.cli.commands.subagent_names import parse_subagent_from_input

# TC-001/002/003: Prefix commands
assert parse_subagent_from_input("/browser go to example.com") == ("browser", "go to example.com")
assert parse_subagent_from_input("/research history of Python") == ("research", "history of Python")
assert parse_subagent_from_input("/claude explain supervised learning") == ("claude", "explain supervised learning")

# TC-004: Inline command
subagent, cleaned = parse_subagent_from_input("Can you /research the history of Python")
assert subagent == "research"
assert "/research" not in cleaned

# TC-005: Case-insensitive
assert parse_subagent_from_input("/BROWSER go to example.com")[0] == "browser"
assert parse_subagent_from_input("/Research history")[0] == "research"

# TC-006/007: No subagent
assert parse_subagent_from_input("read the first 5 lines of pyproject.toml") == (None, "read the first 5 lines of pyproject.toml")
assert parse_subagent_from_input("list all Python files") == (None, "list all Python files")

# TC-008: Multi-command first-wins (browser before research)
subagent, _ = parse_subagent_from_input("/browser open example.com and /research its history")
assert subagent == "browser"

print("All parse_subagent_from_input assertions passed!")
```

---

## Expected Results Summary

| Test Case | Type | Expected Routing | Max Duration |
|-----------|------|-----------------|-------------|
| TC-001 | Explicit prefix `/browser` | → browser subagent | 60s |
| TC-002 | Explicit prefix `/research` | → research subagent | 120s |
| TC-003 | Explicit prefix `/claude` | → claude subagent | 60s |
| TC-004 | Inline `/research` in query | → research subagent | 120s |
| TC-005 | Case-insensitive `/BROWSER` | → browser subagent | 60s |
| TC-006 | No command (filesystem) | → main agent (no subagent) | 30s |
| TC-007 | No command (local analysis) | → main agent (no subagent) | 30s |
| TC-008 | Multi-command first-wins | → browser (first match) | 60s |

---

## Failure Modes to Detect

1. **Slash Command Ignored**: Query with `/browser` goes to main agent instead of browser subagent
2. **Case Sensitivity Bug**: `/BROWSER` fails to route while `/browser` succeeds
3. **Inline Command Not Parsed**: Embedded `/research` in middle of query is not detected
4. **Accidental Subagent Use**: Plain file operation query incorrectly triggers subagent routing
5. **Multi-Command Wrong Winner**: Second slash command wins over the first
6. **Command Not Stripped**: The slash command token remains in the cleaned query sent to the subagent

---

## Benchmark Status Tracking

| Run Date | TC-001 | TC-002 | TC-003 | TC-004 | TC-005 | TC-006 | TC-007 | TC-008 | Notes |
|----------|--------|--------|--------|--------|--------|--------|--------|--------|-------|
| 2026-04-01 | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | Initial run. Fixed 3 bugs: (1) research subagent missing config/context kwargs in resolver, (2) create_research_subagent returned raw graph instead of CompiledSubAgent dict, (3) headless mode not parsing slash commands — fixed in daemon.py |

---

## Related Files

- `src/soothe/ux/cli/commands/subagent_names.py` — `parse_subagent_from_input()`, `BUILTIN_SUBAGENT_NAMES`
- `src/soothe/core/runner/__init__.py` — `astream()` quick path for subagent routing
- `src/soothe/core/resolver/_resolver_tools.py` — `SUBAGENT_FACTORIES` registry
- `src/soothe/subagents/` — individual subagent implementations
- `docs/impl/IG-072-quick-path-subagent-routing.md` — quick path optimization design
- `docs/impl/IG-073-fix-subagent-routing-and-logging.md` — headless mode routing fix
