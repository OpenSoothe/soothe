# AI Agent Guide: Interactive Health Checks

## Quick Start

When a user asks you to check Soothe health, follow this workflow:

### Step 1: Run Automated Checks First

```bash
uv run python .agents/skills/checkhealth/scripts/run_all_checks.py
```

This generates a comprehensive report at `~/.soothe/health_report_<timestamp>.md`.

### Step 2: Analyze the Report

Read the report to identify:
- ❌ Critical issues (require immediate attention)
- ⚠️ Warnings (optional features not working)
- ℹ️ Informational notes (optional services not configured)

### Step 3: Investigate Issues (If Any)

For each issue found, use interactive checks:

#### Example 1: Backend Import Failure

**If report shows**: "Failed to import soothe.backends.durability.postgresql"

**Investigation**:
```python
# Write diagnostic code
try:
    from soothe.backends.durability.postgresql import PostgreSQLDurability
    print("✓ Import succeeded")
except ImportError as e:
    print(f"✗ Import failed: {e}")
    # Check if dependency is installed
    try:
        import asyncpg
        print("  asyncpg is installed")
    except ImportError:
        print("  asyncpg NOT installed - run: uv pip install asyncpg")
```

**Execute**:
```bash
uv run python -c "your diagnostic code here"
```

#### Example 2: Configuration Validation

**If report shows**: Configuration errors

**Investigation**:
```python
from soothe.config import SootheConfig
from pathlib import Path
import yaml

config_path = Path.home() / ".soothe" / "config" / "config.yml"

# Check YAML syntax
with open(config_path) as f:
    try:
        raw = yaml.safe_load(f)
        print("✓ YAML syntax valid")
        print(f"Model providers: {list(raw.get('model', {}).get('providers', {}).keys())}")
    except yaml.YAMLError as e:
        print(f"✗ YAML error: {e}")

# Check Pydantic validation
try:
    config = SootheConfig.from_yaml_file(config_path)
    print("✓ Pydantic validation passed")
except Exception as e:
    print(f"✗ Pydantic validation failed: {e}")
```

#### Example 3: Backend Functionality Test

**If report shows**: Backend not working properly

**Investigation**:
```python
from soothe.backends.durability.json import JsonDurability
from soothe.config import SootheConfig

config = SootheConfig.from_yaml_file("~/.soothe/config/config.yml")
backend = JsonDurability(config.durability.json)

# Test CRUD
test_key = "health_check_test"
test_value = {"test": "data"}

backend.store(test_key, test_value)
retrieved = backend.load(test_key)
backend.delete(test_key)

if retrieved == test_value:
    print("✓ Backend working correctly")
else:
    print(f"✗ Data mismatch: {retrieved} != {test_value}")
```

#### Example 4: Integration Test

**Test multiple components together**:
```python
from soothe.core.runner import Runner
from soothe.config import SootheConfig
from soothe.backends.durability.json import JsonDurability

config = SootheConfig.from_yaml_file("~/.soothe/config/config.yml")

# Test durability
backend = JsonDurability(config.durability.json)
backend.store("test", {"data": "value"})
print("✓ Durability backend working")

# Test runner
runner = Runner(config)
print("✓ Runner initialized")

# Clean up
backend.delete("test")
```

## Diagnostic Patterns

### Pattern 1: Isolate the Problem

```python
# Test component in isolation
from soothe.backends.context.vector import VectorContext

config = load_config()
backend = VectorContext(config.context.vector)

# Minimal test
backend.add("test", {"meta": "data"})
results = backend.query("test", k=1)
print(f"Results: {results}")
```

### Pattern 2: Test Dependencies

```python
# Check if optional dependencies are installed
dependencies = {
    "PostgreSQL": "asyncpg",
    "RocksDB": "rocksdict",
    "Weaviate": "weaviate-client",
}

for feature, package in dependencies.items():
    try:
        __import__(package.replace("-", "_"))
        print(f"✓ {feature} ({package}) installed")
    except ImportError:
        print(f"⚠️ {feature} ({package}) not installed - optional")
```

### Pattern 3: Resource Check

```python
import psutil
import os

process = psutil.Process(os.getpid())

# Check file handles
print(f"Open files: {len(process.open_files())}")

# Check connections
print(f"Network connections: {len(process.connections())}")

# Check memory
print(f"Memory usage: {process.memory_info().rss / 1024 / 1024:.2f} MB")
```

### Pattern 4: Error Handling Test

```python
# Test robustness to errors
from soothe.backends.durability.json import JsonDurability

backend = JsonDurability(config)

# Test invalid input handling
try:
    backend.store(None, "invalid")
    print("⚠️ Should have rejected None key")
except Exception as e:
    print(f"✓ Properly handled invalid input: {type(e).__name__}")

# Test missing key handling
result = backend.load("nonexistent_key")
if result is None:
    print("✓ Returns None for missing keys")
else:
    print(f"⚠️ Unexpected result: {result}")
```

## Best Practices

### DO:
- ✅ Read source code before writing tests
- ✅ Use `uv run python` to ensure dependencies
- ✅ Set PYTHONPATH if needed: `PYTHONPATH=/path/to/src uv run python`
- ✅ Clean up test data after validation
- ✅ Handle exceptions gracefully with try/except
- ✅ Provide clear success/failure indicators (✓/✗)
- ✅ Explain what you're testing and why

### DON'T:
- ❌ Modify production data or configuration
- ❌ Leave test data in databases or stores
- ❌ Assume all dependencies are installed
- ❌ Skip error handling
- ❌ Run infinite loops or long-running operations
- ❌ Make network calls to external services without permission

## Template Script

A template script is available at:
```
.agents/skills/checkhealth/scripts/interactive_check_template.py
```

Run it to test basic functionality:
```bash
uv run python .agents/skills/checkhealth/scripts/interactive_check_template.py
```

Modify the template for custom checks.

## Workflow Summary

```
1. Run automated check
   ↓
2. Read health report
   ↓
3. Identify issues
   ↓
4. Read relevant source code
   ↓
5. Write diagnostic code
   ↓
6. Execute with uv run
   ↓
7. Analyze results
   ↓
8. Iterate if needed
   ↓
9. Report findings
   ↓
10. Recommend fixes
```

## Example Session

```
User: Check Soothe health

AI:
1. Running automated checks...
   [Executes: uv run python scripts/run_all_checks.py]

2. Reading report...
   [Reads: ~/.soothe/health_report_xxx.md]

3. Analysis:
   - Critical: Daemon not running (PID file missing)
   - Warning: PostgreSQL asyncpg not installed
   - Warning: Serper API key not configured

4. Investigating daemon issue...
   [Reads: src/soothe/cli/daemon.py]
   [Writes diagnostic to check socket]

   Diagnostic code:
   ```python
   import socket
   from soothe.cli.daemon import socket_path

   sock_path = socket_path()
   if sock_path.exists():
       print(f"Socket exists: {sock_path}")
   else:
       print(f"Socket missing: {sock_path}")
   ```

   [Executes diagnostic]

5. Root cause: Daemon process is not running.

6. Recommendations:
   - Start daemon: `soothe --daemon`
   - Install asyncpg: `uv pip install asyncpg` (optional)
   - Configure Serper API key if needed (optional)

Health check complete!
```

## Common Issues and Diagnostics

### Issue: "ModuleNotFoundError: No module named 'soothe'"

**Diagnostic**:
```bash
# Set PYTHONPATH
PYTHONPATH=/path/to/Soothe/src uv run python your_script.py

# Or use the template
uv run python .agents/skills/checkhealth/scripts/interactive_check_template.py
```

### Issue: "No module named 'pydantic'"

**Diagnostic**:
```bash
# Install dependencies
make sync-dev

# Or with uv
uv sync
```

### Issue: Backend instantiation fails

**Diagnostic**:
```python
from soothe.config import SootheConfig
from soothe.backends.durability.json import JsonDurability

config = SootheConfig.from_yaml_file("~/.soothe/config/config.yml")
print(f"Durability config: {config.durability}")
print(f"JSON config: {config.durability.json}")

try:
    backend = JsonDurability(config.durability.json)
    print("✓ Backend created successfully")
except Exception as e:
    print(f"✗ Backend creation failed: {e}")
    print(f"  Config type: {type(config.durability.json)}")
    print(f"  Config dict: {config.durability.json.model_dump()}")
```

## Resources

- **Automated Check Scripts**: `.agents/skills/checkhealth/scripts/`
- **Interactive Template**: `scripts/interactive_check_template.py`
- **AI-Driven Check Guide**: `references/AI_DRIVEN_CHECKS.md`
- **Check Categories**: `references/CHECK_CATEGORIES.md`
- **Report Format**: `references/REPORT_FORMAT.md`
