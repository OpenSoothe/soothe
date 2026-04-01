# Soothe Benchmarks

This directory contains benchmarks for validating Soothe agent behavior and performance.

## Purpose

Benchmarks serve as:
- **Verification** for AI agents to validate runtime behavior
- **Regression tests** to catch workspace/context issues
- **Performance baselines** for execution time expectations

## Structure

Each benchmark file follows this format:

```
BM-NNN-brief-title.md
├── Overview
├── Test Cases (TC-NNN)
│   ├── Query
│   ├── Expected Behavior
│   ├── Verification Conditions
│   └── Success Criteria
├── Execution Instructions
└── Status Tracking
```

## Available Benchmarks

| ID | Title | Purpose |
|----|-------|---------|
| [BM-001](BM-001-workspace-injection.md) | Workspace Injection | Verify workspace context propagation |

## Running Benchmarks

### Manual Execution

```bash
# Run a specific test case
soothe --no-tui -p "<query from test case>"

# Verify conditions in output
```

### Automated Execution

```python
# Use the verification script template from each benchmark
python verify_benchmark.py BM-001
```

## Adding New Benchmarks

1. Create `BM-NNN-brief-title.md`
2. Define test cases with:
   - Query (what to ask)
   - Expected behavior
   - Verification conditions (checklist)
   - Success criteria (pass/fail conditions)
3. Add execution instructions
4. Update this README

## Benchmark Naming Convention

- **BM-NNN**: Benchmark number (001-999)
- **TC-NNN**: Test case within benchmark
- **VC-NNN**: Verification condition (optional)

## Status Icons

- ✅ Pass
- ❌ Fail
- ⚠️ Partial
- 🔍 Needs Review