# IG-062: Health Check CLI Command Implementation

**Status**: In Progress
**Created**: 2026-03-26
**RFC Reference**: N/A (new feature)

## Objective

Add a `soothe checkhealth` CLI command that validates configuration and checks backend service availability (PostgreSQL, LLM providers, vector stores, SOOTHE_HOME).

## Background

This implementation guide documents the planned health check CLI command. Note: The reference to legacy scripts in `skills/soothe-checkhealth/scripts/` is historical - those scripts have been removed.

## Design

### Architecture

Refactor existing scripts into a reusable library at `src/soothe/core/health/`, then create a CLI wrapper at `src/soothe/ux/cli/commands/health_cmd.py`.

### Module Structure

```
src/soothe/core/health/
├── __init__.py             # Public API: HealthChecker
├── checker.py              # HealthChecker orchestration class
├── models.py               # CheckResult, CategoryResult, HealthReport
├── formatters.py           # Output formatters (text, JSON, markdown)
└── checks/                 # Individual check implementations
    ├── config_check.py     # Config validation
    ├── daemon_check.py     # Daemon health
    ├── protocols_check.py  # Protocol backends
    ├── persistence_check.py # PostgreSQL/RocksDB/filesystem
    ├── vector_stores_check.py # Vector store connectivity
    ├── providers_check.py  # LLM provider connectivity
    ├── mcp_check.py        # MCP server checks
    └── external_apis_check.py # External API connectivity
```

### Check Categories

1. **Configuration** - Config file validation, env vars, SOOTHE_HOME
2. **Daemon** - Socket responsiveness, PID, process health
3. **Persistence** - PostgreSQL connection, RocksDB, filesystem
4. **Vector Stores** - Connection tests for configured stores
5. **LLM Providers** - API key validation and test calls
6. **MCP Servers** - Server availability and health
7. **Protocols** - Backend imports
8. **External APIs** - OpenAI, Google, Tavily, Serper, Jina

### Output Formats

- Terminal: Colored human-readable output
- JSON: Machine-readable for scripting
- Quiet: Exit codes only

### Exit Codes

- 0: All checks passed
- 1: Warnings present
- 2: Critical issues

## Implementation Plan

### Phase 1: Foundation

**Files**:
- `src/soothe/core/health/models.py`
- `src/soothe/core/health/formatters.py`
- `src/soothe/core/health/__init__.py`
- `src/soothe/core/health/checks/__init__.py`

**Tasks**:
- Create data models (CheckStatus, CheckResult, CategoryResult, HealthReport)
- Implement output formatters
- Create HealthChecker skeleton

### Phase 2: Port Existing Checks

**Files**:
- `src/soothe/core/health/checker.py`
- `src/soothe/core/health/checks/daemon_check.py`
- `src/soothe/core/health/checks/protocols_check.py`
- `src/soothe/core/health/checks/persistence_check.py`
- `src/soothe/core/health/checks/external_apis_check.py`

**Tasks**:
- Implement health check logic from scratch (legacy scripts removed)
- Add config parameter to checks
- Wire into HealthChecker methods

### Phase 3: Config-Driven Checks

**Files**:
- `src/soothe/core/health/checks/config_check.py`
- `src/soothe/core/health/checks/providers_check.py`
- `src/soothe/core/health/checks/vector_stores_check.py`
- `src/soothe/core/health/checks/mcp_check.py`

**Tasks**:
- Implement config validation
- Implement LLM provider connectivity tests
- Implement vector store connection tests
- Implement MCP server checks

### Phase 4: CLI Integration

**Files**:
- `src/soothe/ux/cli/commands/health_cmd.py`
- `src/soothe/ux/cli/main.py`

**Tasks**:
- Implement CLI command with options
- Add to main CLI app
- Handle exit codes

### Phase 5: Testing

**Files**:
- `tests/core/health/test_checker.py`
- `tests/cli/test_health_cmd.py`

**Tasks**:
- Unit tests for check modules
- Integration tests for CLI
- Test exit codes and output formats

### Phase 6: Documentation

**Tasks**:
- Update user guide
- Add examples to README

## Verification

After implementation:

1. `soothe checkhealth` outputs colored report
2. `soothe checkhealth --output json` outputs valid JSON
3. `soothe checkhealth --quiet` returns exit code only
4. `soothe checkhealth --check daemon` runs specific checks
5. Invalid config reports errors with exit code 2
6. `./scripts/verify_finally.sh` passes
7. PostgreSQL unavailability reports warning
8. Invalid API keys report errors

## Success Criteria

- [ ] All check categories implemented
- [ ] Terminal, JSON, and quiet output modes working
- [ ] Exit codes correct
- [ ] Config-driven checks functional
- [ ] All tests passing
- [ ] Documentation updated

## Estimated Effort

~18 hours (2-3 days)

## Notes

- Maintain backward compatibility with existing skill scripts
- Use async execution for performance
- Handle partial failures gracefully
- Provide actionable remediation messages