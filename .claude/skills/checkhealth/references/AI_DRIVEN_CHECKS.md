# AI-Driven Health Checks

## Overview

In addition to automated scripts, AI agents can perform interactive health checks through coding and testing. This approach provides deeper insights and can diagnose complex issues that automated scripts cannot detect.

## When to Use AI-Driven Checks

Use AI-driven interactive checks when:
- Automated scripts show issues but the root cause is unclear
- You need to validate specific functionality in depth
- Testing integration between components
- Verifying edge cases and error handling
- Diagnosing configuration problems
- Testing runtime behavior under specific conditions

## Interactive Check Procedures

### 1. Daemon Health Validation

**Objective**: Test daemon responsiveness and command execution

**Procedure**:
```python
# Test daemon socket communication
import socket
import json

sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
sock.connect("/Users/xiamingchen/.soothe/soothe.sock")

# Send a ping command
sock.send(json.dumps({"command": "ping"}).encode())
response = sock.recv(4096)
print(json.loads(response))

sock.close()
```

**What to check**:
- Socket connection succeeds
- Commands are acknowledged
- Response times are reasonable
- No errors in daemon logs

### 2. Protocol Backend Instantiation Test

**Objective**: Verify protocol backends can be instantiated and used

**Procedure**:
```python
# Test creating and using a protocol backend
from soothe.backends.durability.json import JsonDurability
from soothe.config import SootheConfig

config = SootheConfig.from_yaml_file("~/.soothe/config/config.yml")
backend = JsonDurability(config.durability)

# Test basic operations
test_key = "health_check_test"
test_value = {"test": "data", "timestamp": "2024-01-01"}

backend.store(test_key, test_value)
retrieved = backend.load(test_key)
backend.delete(test_key)

assert retrieved == test_value, f"Retrieved {retrieved} != {test_value}"
print("✓ JSON durability backend working correctly")
```

**What to check**:
- Backend instantiation succeeds
- Basic CRUD operations work
- Data integrity is maintained
- No memory leaks or resource issues

### 3. Configuration Validation

**Objective**: Deep analysis of configuration file

**Procedure**:
```python
# Load and validate configuration in detail
from soothe.config import SootheConfig
import yaml

config_path = Path.home() / ".soothe" / "config" / "config.yml"

# Parse YAML structure
with open(config_path) as f:
    raw_config = yaml.safe_load(f)

# Validate each section
print("Model Provider Config:")
print(f"  - Default provider: {raw_config.get('model', {}).get('default_provider')}")

print("\nDurability Backends:")
for name, settings in raw_config.get('durability', {}).items():
    print(f"  - {name}: {settings.get('type', 'unknown')}")

# Load via Pydantic for schema validation
config = SootheConfig.from_yaml_file(config_path)
print("\n✓ Configuration loads successfully via Pydantic")
```

**What to check**:
- YAML syntax is valid
- All required fields present
- Schema validation passes
- No deprecated or invalid settings

### 4. Integration Test: Full Workflow

**Objective**: Test end-to-end workflow across multiple components

**Procedure**:
```python
# Test a complete agent execution workflow
from soothe.core.runner import Runner
from soothe.config import SootheConfig

config = SootheConfig.from_yaml_file("~/.soothe/config/config.yml")

# Create a simple test agent
test_skill = """
---
name: health_test
description: Test skill for health check
---
# Health Test Skill

This is a simple test skill.
"""

# Try to create runner and execute
runner = Runner(config)
result = runner.run_skill("health_test", "Test input")

print(f"✓ Workflow executed: {result}")
```

**What to check**:
- Components integrate correctly
- Data flows through the system
- No circular dependencies
- Error handling works properly

### 5. Resource Leak Detection

**Objective**: Check for file handles, connections, and memory leaks

**Procedure**:
```python
import psutil
import os

# Track resources before operations
process = psutil.Process(os.getpid())
files_before = len(process.open_files())
connections_before = len(process.connections())

# Perform operations
from soothe.backends.durability.postgresql import PostgreSQLDurability
backend = PostgreSQLDurability(config.durability.postgresql)
backend.store("test", {"data": "value"})
backend.close()

# Check resources after
files_after = len(process.open_files())
connections_after = len(process.connections())

print(f"File handles: {files_before} -> {files_after}")
print(f"Connections: {connections_before} -> {connections_after}")

if files_after > files_before:
    print("⚠️ Possible file handle leak detected!")
if connections_after > connections_before:
    print("⚠️ Possible connection leak detected!")
```

**What to check**:
- Resources are properly released
- No growing resource usage over time
- Cleanup handlers execute correctly

### 6. Error Handling Validation

**Objective**: Test system robustness to errors

**Procedure**:
```python
# Test error handling in various scenarios
from soothe.backends.context.vector import VectorContext

# Test 1: Invalid configuration
try:
    backend = VectorContext({"invalid": "config"})
    print("⚠️ Should have raised error for invalid config")
except Exception as e:
    print(f"✓ Properly rejected invalid config: {type(e).__name__}")

# Test 2: Missing required data
try:
    result = backend.query(None)
    print("⚠️ Should have raised error for None query")
except Exception as e:
    print(f"✓ Properly handled None query: {type(e).__name__}")

# Test 3: Network timeout simulation
import asyncio

async def test_timeout():
    try:
        # Simulate timeout scenario
        await asyncio.wait_for(
            asyncio.sleep(10),
            timeout=0.1
        )
    except asyncio.TimeoutError:
        print("✓ Timeout handling works correctly")

asyncio.run(test_timeout())
```

**What to check**:
- Errors are caught and handled gracefully
- Error messages are informative
- System remains stable after errors
- No cascading failures

## AI Agent Workflow for Health Checks

### Phase 1: Automated Checks
1. Run automated scripts first: `uv run python scripts/run_all_checks.py`
2. Analyze the generated report
3. Identify any issues or warnings

### Phase 2: Interactive Investigation
For each issue found:

1. **Read relevant code**:
   - Use `Read` tool to examine source files
   - Check implementation details
   - Look for potential bugs or issues

2. **Write diagnostic code**:
   - Create test scripts to reproduce issues
   - Test specific functionality in isolation
   - Validate assumptions

3. **Execute tests**:
   - Run diagnostic code with `uv run python`
   - Capture output and errors
   - Analyze results

4. **Iterate**:
   - Refine tests based on findings
   - Test edge cases
   - Verify fixes

### Phase 3: Reporting

Document findings:
- What was tested
- How it was tested (code snippets)
- Results and observations
- Root cause analysis
- Recommendations

## Example Interactive Check Session

```
User: Check why PostgreSQL backend is failing

AI Agent:
1. Read health report - shows PostgreSQL authentication error
2. Read configuration file - check PostgreSQL settings
3. Read PostgreSQL backend code - understand connection logic
4. Write diagnostic script:
   - Test connection string
   - Verify credentials
   - Check database exists
5. Execute script - identifies wrong password
6. Report: "PostgreSQL authentication failing due to incorrect password in config"
7. Recommendation: Update password in config.yml or create database user
```

## Best Practices

### For AI Agents

1. **Start with automated checks** - don't reinvent the wheel
2. **Read code before testing** - understand what you're testing
3. **Test incrementally** - one component at a time
4. **Handle imports gracefully** - use try/except for optional dependencies
5. **Clean up resources** - close connections, files, etc.
6. **Document everything** - future health checks benefit from notes

### For Writing Diagnostic Code

1. Use `PYTHONPATH=/path/to/src` or run from repo root
2. Use `uv run python` to ensure dependencies
3. Wrap in try/except to catch errors gracefully
4. Print clear status messages (✓ for success, ⚠️ for warnings, ✗ for failures)
5. Clean up test data after validation
6. Use context managers for resources

## Common Diagnostic Patterns

### Pattern 1: Import Test
```python
try:
    from soothe.backends.X import Y
    backend = Y(config)
    print("✓ Backend imports and instantiates")
except ImportError as e:
    print(f"✗ Import failed: {e}")
except Exception as e:
    print(f"✗ Instantiation failed: {e}")
```

### Pattern 2: Connection Test
```python
import socket
sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
try:
    sock.connect(socket_path)
    sock.close()
    print("✓ Socket connection successful")
except Exception as e:
    print(f"✗ Socket connection failed: {e}")
```

### Pattern 3: Configuration Test
```python
from soothe.config import SootheConfig
try:
    config = SootheConfig.from_yaml_file(config_path)
    print("✓ Configuration valid")
    print(f"  - Providers: {list(config.model.providers.keys())}")
    print(f"  - Durability: {config.durability.default_backend}")
except Exception as e:
    print(f"✗ Configuration invalid: {e}")
```

### Pattern 4: Functional Test
```python
# Store
backend.store("test_key", {"data": "test"})
# Retrieve
data = backend.load("test_key")
assert data == {"data": "test"}
# Delete
backend.delete("test_key")
assert backend.load("test_key") is None
print("✓ CRUD operations work correctly")
```

## Integration with Automated Checks

The AI-driven checks complement automated scripts:

| Aspect | Automated Scripts | AI-Driven Checks |
|--------|------------------|------------------|
| Speed | Fast | Variable |
| Depth | Shallow | Deep |
| Flexibility | Fixed | Adaptable |
| Root Cause | Limited | Extensive |
| Context Awareness | None | Full |
| Code Understanding | None | Complete |

Use both together for comprehensive health validation.
