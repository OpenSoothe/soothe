# BM-001: Workspace Injection and Agent Behavior Benchmark

> **Purpose**: Verify that workspace context is correctly propagated to all agent components during runtime execution.
>
> **Last Updated**: 2026-04-01
>
> **Status**: Active

---

## Overview

This benchmark validates that when a user runs a query from a specific directory, the agent:

1. Correctly identifies the workspace directory
2. Uses the workspace for file operations, shell commands, and planning
3. Does not fall back to daemon default workspace incorrectly

---

## Test Cases

### TC-001: Basic Workspace Identification

**Query**: `"what is the current directory"`

**Expected Behavior**:
- Agent executes `pwd` or similar command
- Returns the user's actual working directory, not daemon default

**Verification Conditions**:
- [ ] Response contains the correct workspace path (e.g., `/Users/chenxm/Workspace/Soothe`)
- [ ] Response does NOT contain daemon default path (`~/.soothe/Workspace`)
- [ ] Step completes in < 15 seconds
- [ ] Tool call count is 1-2 (minimal, direct execution)

**Success Criteria**:
```
Response includes: /Users/chenxm/Workspace/Soothe
Response excludes: .soothe/Workspace (unless that IS the workspace)
```

---

### TC-002: File Operations in Workspace

**Query**: `"read the first 10 lines of README.md"`

**Expected Behavior**:
- Agent locates README.md in the workspace directory
- Reads and returns content from the correct file
- Does not search in system directories or home directory

**Verification Conditions**:
- [ ] File path referenced is `{workspace}/README.md`
- [ ] Content returned matches actual file content
- [ ] No errors about "file not found" or "directory is empty"
- [ ] Step count <= 3 (efficient planning)
- [ ] Total execution time < 60 seconds

**Success Criteria**:
```
File read from: /Users/chenxm/Workspace/Soothe/README.md
Content starts with: # Soothe
```

---

### TC-003: Directory Listing in Workspace

**Query**: `"list files in the current directory"`

**Expected Behavior**:
- Agent lists files in the workspace directory
- Returns actual project files, not root filesystem or empty directory

**Verification Conditions**:
- [ ] Listed files include project files (e.g., `README.md`, `src/`, `pyproject.toml`)
- [ ] Listed files are NOT root filesystem entries (`/Applications`, `/System`, etc.)
- [ ] Listed directory is NOT empty (unless workspace is actually empty)
- [ ] Step count <= 2

**Success Criteria**:
```
Response includes at least 3 of:
- README.md
- src/
- pyproject.toml
- tests/
- docs/

Response excludes:
- /Applications
- /System
- /Library
```

---

### TC-004: Planner Workspace Awareness

**Query**: `"find and read the main configuration file"`

**Expected Behavior**:
- Planner creates a plan that searches in the workspace
- Does not plan to search in system directories or home directory broadly
- Uses file tools (read_file, list_files) not browser subagent for local files

**Verification Conditions**:
- [ ] Plan steps reference workspace-relative paths
- [ ] Plan does not include "search in home directory" or "navigate to filesystem root"
- [ ] Planner uses appropriate tools (file tools for local files)
- [ ] Total execution time < 45 seconds

**Success Criteria**:
```
Plan includes workspace-relative operations:
- "Read pyproject.toml in the project root"
- "List config files in {workspace}/config/"

Plan excludes:
- "Navigate to /Users/home"
- "Search in system directories"
```

---

### TC-005: Shell Command Workspace

**Query**: `"run ls -la and show the output"`

**Expected Behavior**:
- Shell executes in the workspace directory
- Output shows workspace files, not root filesystem

**Verification Conditions**:
- [ ] Output shows workspace contents
- [ ] Output includes files like `README.md`, `src/`, `pyproject.toml`
- [ ] Output does NOT show root filesystem entries (`/Applications`, etc.)
- [ ] Shell `cd` to workspace happens before command execution

**Success Criteria**:
```
ls output includes: README.md, src/, pyproject.toml
ls output excludes: Applications, Library, System
```

---

### TC-006: Multi-Step Workspace Consistency

**Query**: `"analyze the project structure and summarize the main components"`

**Expected Behavior**:
- All steps operate within the workspace
- File reads use correct paths
- No "file not found" errors for files that exist in workspace

**Verification Conditions**:
- [ ] All file operations reference workspace paths
- [ ] No step fails due to "file not found" for files that exist
- [ ] Summary accurately reflects project structure
- [ ] Execution time < 90 seconds

**Success Criteria**:
```
Summary mentions actual project components:
- src/soothe/ (source code)
- tests/ (test files)
- docs/ (documentation)

No errors about missing files that exist in workspace.
```

---

## Execution Instructions

### For AI Agent Execution

1. **Run each test case sequentially**
2. **Capture the CLI output** for each query
3. **Check each verification condition** (mark as passed/failed)
4. **Record execution time** for each test case
5. **Generate summary report** with pass/fail counts

### Command Format

```bash
# Execute test case
soothe --no-tui -p "<query>"

# Capture output and check conditions
```

---

## Verification Script Template

```python
import subprocess
import time

def run_benchmark():
    results = []

    test_cases = [
        {
            "id": "TC-001",
            "query": "what is the current directory",
            "must_contain": ["/Users/chenxm/Workspace/Soothe"],
            "must_not_contain": [".soothe/Workspace"],
            "max_duration_s": 15,
        },
        {
            "id": "TC-002",
            "query": "read the first 10 lines of README.md",
            "must_contain": ["# Soothe"],
            "must_not_contain": ["file not found", "directory is empty"],
            "max_duration_s": 60,
        },
        # ... additional test cases
    ]

    for tc in test_cases:
        start = time.time()
        result = subprocess.run(
            ["soothe", "--no-tui", "-p", tc["query"]],
            capture_output=True,
            text=True,
            timeout=tc["max_duration_s"] * 2,
        )
        duration = time.time() - start

        output = result.stdout + result.stderr
        passed = all(
            phrase in output for phrase in tc["must_contain"]
        ) and not any(
            phrase in output for phrase in tc["must_not_contain"]
        )

        results.append({
            "id": tc["id"],
            "passed": passed,
            "duration_s": round(duration, 1),
        })

    return results
```

---

## Expected Results Summary

| Test Case | Expected Duration | Key Verification |
|-----------|-------------------|------------------|
| TC-001 | < 15s | Correct directory returned |
| TC-002 | < 60s | File found and read |
| TC-003 | < 30s | Correct files listed |
| TC-004 | < 45s | Planner uses workspace |
| TC-005 | < 20s | Shell runs in workspace |
| TC-006 | < 90s | Consistent multi-step |

---

## Failure Modes to Detect

1. **Daemon Default Fallback**: Agent uses `~/.soothe/Workspace` instead of actual workspace
2. **Root Filesystem Access**: Agent lists/searches in `/` or system directories
3. **File Not Found**: Agent cannot find files that exist in workspace
4. **Empty Directory**: Agent reports workspace is empty when it's not
5. **Browser for Local Files**: Agent uses browser subagent for local file operations
6. **Home Directory Search**: Agent searches broadly in `~` instead of workspace

---

## Logs to Verify

After running benchmarks, check daemon logs:

```bash
# Check workspace resolution
grep -E "(workspace|LangGraph configurable)" ~/.soothe/logs/soothe.log | tail -20

# Should see entries like:
# "Using workspace from LangGraph configurable: /Users/chenxm/Workspace/Soothe"
# "Changed to workspace: /Users/chenxm/Workspace/Soothe"
```

---

## Benchmark Status Tracking

| Run Date | TC-001 | TC-002 | TC-003 | TC-004 | TC-005 | TC-006 | Notes |
|----------|--------|--------|--------|--------|--------|--------|-------|
| 2026-04-01 | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | Initial verification |

---

## Related Files

- `src/soothe/tools/file_ops/implementation.py` - `_get_effective_work_dir()`
- `src/soothe/tools/execution/implementation.py` - `_get_effective_workspace()`
- `src/soothe/backends/planning/simple.py` - `_build_plan_prompt()`
- `src/soothe/protocols/planner.py` - `PlanContext.workspace`

---

## Changelog

| Date | Change |
|------|--------|
| 2026-04-01 | Initial benchmark creation |