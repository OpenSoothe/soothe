---
name: checkhealth
description: Comprehensive health check for Soothe daemon, protocols, persistence, subagents, and external integrations. Supports both automated scripts and AI-driven interactive checks. Use when diagnosing issues, validating configurations, or verifying system health.
metadata:
  author: soothe
  version: "2.0"
compatibility: Requires Soothe development environment with uv package manager
---

# Soothe Health Check Skill

## Overview

This skill provides **dual-mode health checking** for Soothe:

1. **Automated Scripts**: Fast, comprehensive checks using Python scripts
2. **AI-Driven Interactive Checks**: Deep analysis through coding and testing by AI agents

It validates:

- **Core Infrastructure**: Daemon process, model providers, configuration
- **Protocol Backends**: Context, memory, planner, policy, durability, vector store, remote agent protocols
- **Persistence Layer**: PostgreSQL, RocksDB, file system
- **Subagent System**: Subagent imports, dependencies, generated registry
- **External Integrations**: MCP servers, browser runtime, external APIs
- **Runtime Health**: Thread management, resource cleanup, logging

## Prerequisites

- Soothe development environment set up
- `uv` package manager installed
- Dependencies installed (run `make sync-dev` if needed)
- Valid configuration file at `~/.soothe/config/config.yml` (or specified path)
- Some checks require the daemon to be running, others work with stopped daemon

## Documentation

- **[AI_AGENT_GUIDE.md](AI_AGENT_GUIDE.md)**: Quick reference for AI agents performing interactive checks
- **[references/AI_DRIVEN_CHECKS.md](references/AI_DRIVEN_CHECKS.md)**: Comprehensive procedures for AI-driven health checks
- **[references/CHECK_CATEGORIES.md](references/CHECK_CATEGORIES.md)**: Detailed check specifications
- **[references/REPORT_FORMAT.md](references/REPORT_FORMAT.md)**: Report template details

## Quick Start

If dependencies are not installed, first run:

```bash
make sync-dev
```

Then run a comprehensive health check:

```bash
uv run python .agents/skills/checkhealth/scripts/run_all_checks.py
```

This automatically sets PYTHONPATH to use the current code repository and generates a health report at `~/.soothe/health_report_<timestamp>.md`.

This generates a health report at `~/.soothe/health_report_<timestamp>.md`.

## Two Modes of Operation

### Mode 1: Automated Script Checks

Run Python scripts for fast, comprehensive validation:

```bash
# Quick automated health check
uv run python .agents/skills/checkhealth/scripts/run_all_checks.py
```

**Best for**:
- Initial health assessment
- CI/CD integration
- Quick validation
- Routine monitoring

### Mode 2: AI-Driven Interactive Checks

AI agents perform deep analysis through coding and testing:

**When to use**:
- Automated scripts show issues but root cause is unclear
- Need to validate specific functionality in depth
- Testing integration between components
- Diagnosing complex configuration problems
- Verifying edge cases and error handling

**How AI agents check health**:
1. Run automated scripts first to identify issues
2. Read relevant source code to understand implementations
3. Write and execute diagnostic code to test hypotheses
4. Analyze results and iterate
5. Provide detailed findings and recommendations

See [references/AI_DRIVEN_CHECKS.md](references/AI_DRIVEN_CHECKS.md) for detailed procedures and patterns.

## Check Categories

| Category | Checks | Description |
|----------|--------|-------------|
| **Core Infrastructure** | 4 | Daemon process, model providers, configuration |
| **Protocol Backends** | 7 | Context, memory, planner, policy, durability, vector store, remote agents |
| **Persistence Layer** | 3 | Database connectivity, storage availability |
| **Subagent System** | 3 | Subagent imports, dependencies, registry |
| **External Integrations** | 4 | MCP servers, browser, external APIs |
| **Runtime Health** | 3 | Thread management, cleanup, logging |

See [references/CHECK_CATEGORIES.md](references/CHECK_CATEGORIES.md) for detailed check specifications.

## Running Checks

### Automated Script Checks

#### Individual Category Checks

Each category has a dedicated script in `scripts/`:

```bash
# Check daemon process and socket
uv run python .agents/skills/checkhealth/scripts/check_daemon.py

# Validate protocol backends
uv run python .agents/skills/checkhealth/scripts/check_protocols.py

# Test persistence layer
uv run python .agents/skills/checkhealth/scripts/check_persistence.py

# Check external API connectivity
uv run python .agents/skills/checkhealth/scripts/check_external_apis.py
```

Each script outputs JSON with status and details:

```json
{
  "category": "daemon",
  "status": "healthy",
  "checks": [
    {
      "name": "daemon_process",
      "status": "ok",
      "message": "Daemon running with PID 12345"
    }
  ]
}
```

#### Full Health Check

The main orchestrator runs all checks in sequence:

```bash
uv run python .agents/skills/checkhealth/scripts/run_all_checks.py [--config PATH] [--output PATH]
```

The script automatically:
- Sets PYTHONPATH to use the current code repository
- Uses `uv run` to ensure dependencies are available
- Runs all checks in sequence

Options:
- `--config PATH`: Custom config file path (default: `~/.soothe/config/config.yml`)
- `--output PATH`: Custom output report path (default: auto-generated)

### AI-Driven Interactive Checks

AI agents can perform sophisticated health checks by:

1. **Reading source code** to understand implementations
2. **Writing diagnostic scripts** to test specific functionality
3. **Executing tests** with `uv run python` to validate behavior
4. **Analyzing results** and providing recommendations

#### Example: Check Backend Functionality

```python
# AI agent creates diagnostic script
from soothe.backends.durability.json import JsonDurability
from soothe.config import SootheConfig

# Load configuration
config = SootheConfig.from_yaml_file("~/.soothe/config/config.yml")

# Test backend
backend = JsonDurability(config.durability.json)
backend.store("health_check", {"status": "testing"})
result = backend.load("health_check")
backend.delete("health_check")

print(f"✓ Backend working: {result}")
```

#### Example: Validate Configuration

```python
# AI agent validates config in detail
from soothe.config import SootheConfig
import yaml

# Check YAML structure
config_path = Path.home() / ".soothe" / "config" / "config.yml"
with open(config_path) as f:
    raw = yaml.safe_load(f)

print(f"Model providers: {list(raw.get('model', {}).get('providers', {}).keys())}")
print(f"Durability backends: {list(raw.get('durability', {}).keys())}")

# Validate with Pydantic
config = SootheConfig.from_yaml_file(config_path)
print("✓ Configuration valid")
```

#### Example: Test Integration

```python
# AI agent tests multi-component integration
from soothe.core.runner import Runner
from soothe.config import SootheConfig

config = SootheConfig.from_yaml_file("~/.soothe/config/config.yml")
runner = Runner(config)

# Test agent creation and execution
result = runner.run_skill("test_skill", "test input")
print(f"✓ Integration test passed: {result}")
```

See [references/AI_DRIVEN_CHECKS.md](references/AI_DRIVEN_CHECKS.md) for comprehensive procedures and patterns.

## Interpreting Results

### Exit Codes

- **0**: All checks passed (healthy)
- **1**: Warnings detected (non-critical issues)
- **2**: Critical failures detected (requires attention)

### Status Indicators

- `[OK]`: Check passed
- `[INFO]`: Informational notice (not a failure)
- `[WARN]`: Warning (non-critical issue)
- `[ERR]`: Error (critical failure)

### Report Format

The generated report includes:

1. **Header**: Timestamp, Soothe version, config file path
2. **Summary**: Overall health status, counts by category
3. **Detailed Results**: Per-category breakdown with pass/fail status
4. **Issues Found**: Critical issues, warnings, informational notes
5. **Recommendations**: Suggested actions for failures

See [references/REPORT_FORMAT.md](references/REPORT_FORMAT.md) for report template details.

## Common Use Cases

### Quick Automated Health Check

```bash
# Fast comprehensive check
uv run python .agents/skills/checkhealth/scripts/run_all_checks.py
```

### AI-Driven Deep Investigation

When automated checks show issues, AI agents can investigate:

**Example: Diagnose PostgreSQL Connection Issue**

```
User: The health report shows PostgreSQL authentication failing

AI Agent:
1. Reads check_protocols.py output - sees authentication error
2. Reads config.yml to check PostgreSQL settings
3. Reads PostgreSQL backend code (src/soothe/backends/durability/postgresql.py)
4. Writes diagnostic script:
   ```python
   from soothe.config import SootheConfig
   import asyncio
   import asyncpg

   config = SootheConfig.from_yaml_file("~/.soothe/config/config.yml")
   pg_config = config.durability.postgresql

   async def test_connection():
       try:
           conn = await asyncpg.connect(
               host=pg_config.host,
               port=pg_config.port,
               user=pg_config.user,
               password=pg_config.password,
               database=pg_config.database
           )
           print("✓ Connection successful")
           await conn.close()
       except Exception as e:
           print(f"✗ Connection failed: {e}")

   asyncio.run(test_connection())
   ```
5. Executes script with `uv run python diagnose.py`
6. Analyzes error output
7. Provides root cause and fix
```

**Example: Test Backend Integration**

```python
# AI agent writes integration test
from soothe.backends.durability.json import JsonDurability
from soothe.backends.context.vector import VectorContext
from soothe.config import SootheConfig

config = SootheConfig.from_yaml_file("~/.soothe/config/config.yml")

# Test durability backend
durability = JsonDurability(config.durability.json)
durability.store("test_key", {"data": "test"})
result = durability.load("test_key")
print(f"✓ Durability backend: {result}")

# Test context backend
context = VectorContext(config.context.vector)
context.add("test query", {"metadata": "test"})
results = context.query("test", k=1)
print(f"✓ Context backend: {len(results)} results")

# Clean up
durability.delete("test_key")
```

### Pre-flight Check Before Running

```bash
# Ensure everything is configured correctly
uv run python .agents/skills/checkhealth/scripts/run_all_checks.py
```

### Diagnose Daemon Issues

```bash
# Check daemon status specifically
uv run python .agents/skills/checkhealth/scripts/check_daemon.py
```

### Validate Configuration Changes

```bash
# After updating config.yml, verify all backends load correctly
uv run python .agents/skills/checkhealth/scripts/check_protocols.py
```

### Check External Dependencies

```bash
# Verify API keys and connectivity
uv run python .agents/skills/checkhealth/scripts/check_external_apis.py
```

## Architecture

The health check system operates in two complementary modes:

### Automated Scripts

Fast, deterministic checks following these principles:

1. **Non-invasive**: Checks only perform read operations, never modify state
2. **Progressive**: Run quick checks first, expensive checks later
3. **Graceful degradation**: If a check cannot run, report as "skipped" rather than failing
4. **Actionable**: Each failure includes remediation suggestions

All check scripts:
- Output JSON for easy parsing
- Use colored output for terminal readability
- Follow the exit code convention (0/1/2)
- Handle missing dependencies gracefully

### AI-Driven Interactive Checks

Deep, adaptive analysis with full context awareness:

1. **Context-rich**: AI reads source code to understand implementations
2. **Adaptive**: Tests are tailored to specific issues and configurations
3. **Interactive**: Can iterate and refine based on results
4. **Root cause analysis**: AI can trace issues through the codebase
5. **Fix validation**: AI can write and test fixes in real-time

AI agents can:
- Read source code and configuration files
- Write and execute diagnostic Python code
- Analyze output and error messages
- Iterate on tests to isolate issues
- Provide detailed explanations and recommendations

### Mode Comparison

| Aspect | Automated Scripts | AI-Driven Checks |
|--------|------------------|------------------|
| **Speed** | Fast (< 1 min) | Variable (5-30 min) |
| **Depth** | Surface-level | Deep analysis |
| **Flexibility** | Fixed checks | Fully adaptable |
| **Root Cause** | Limited insight | Extensive analysis |
| **Context** | None | Full codebase access |
| **Best For** | Routine checks, CI/CD | Complex issues, debugging |

Use automated scripts for quick validation, then AI-driven checks for deep investigation when issues are found.

## Implementation Notes

The skill leverages existing Soothe patterns:

- `SootheDaemon.is_running()` from `src/soothe/cli/daemon.py` for daemon checks
- Protocol backend imports for validation
- Configuration loading from `src/soothe/config.py`
- Health check patterns similar to `RemoteAgentProtocol.health_check()`

All scripts are standalone Python with minimal dependencies beyond the standard library and Soothe's existing requirements.
