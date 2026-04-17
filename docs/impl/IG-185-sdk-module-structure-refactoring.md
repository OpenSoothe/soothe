# IG-185: SDK Module Structure Refactoring

**Status**: 🟡 Pending Execution
**Created**: 2026-04-17
**RFC**: RFC-610 (SDK Module Structure Refactoring)
**Dependencies**: IG-173 (CLI-Daemon Split), IG-174 (CLI Import Violations), IG-175 (WebSocket Migration)
**Priority**: High - Architecture cleanup for maintainability and ecosystem alignment
**Estimated Duration**: 1-2 weeks (no backward compatibility)
**Breaking Change**: Yes - v0.4.0 version bump required

---

## Overview

Refactor soothe-sdk module structure to align with langchain-core patterns and improve organization. This implementation reorganizes 32 files into purpose packages (plugin/, client/, ux/, utils/, protocols/) while keeping core concepts at root, reducing root clutter from 15 files to 3, and eliminating 5 files through strategic merges and splits.

**Key Objectives:**
1. Match langchain/deepagents patterns for ecosystem familiarity
2. Establish clear purpose boundaries (plugin API, client utilities, UX, utils)
3. Eliminate flat 15-file root structure
4. Create minimal __init__.py (version-only, no re-exports)
5. Complete in 1-2 weeks with no backward compatibility layer

**Breaking Impact:**
- All import paths change (~110-130 statements in 45-65 files)
- Third-party plugins require manual import updates
- Version bump: soothe-sdk v0.3.0 → v0.4.0, soothe-cli v0.1.0 → v0.2.0, soothe v0.3.0 → v0.4.0

---

## Pre-Implementation Verification

### Baseline Tests

**Run before starting:**
```bash
# Verify current state
./scripts/verify_finally.sh

# Expected: All 900+ tests pass, zero linting errors
```

### Import Analysis

**Verify no circular imports:**
```bash
# Check current import graph
python3 << 'EOF'
import sys
from pathlib import Path

sdk_root = Path("packages/soothe-sdk/src/soothe_sdk")
print("Current SDK structure:")
for f in sorted(sdk_root.rglob("*.py")):
    if f.name != "__pycache__":
        print(f"  {f.relative_to(sdk_root)}")
EOF
```

**Expected output:** 32 files (15 root + 17 subpackages)

### Dependency Count

**Check current imports in dependent packages:**
```bash
# Count import statements to update
grep -r "from soothe_sdk import" packages/soothe-cli/src/ | wc -l  # Expected: ~20-25
grep -r "from soothe_sdk import" packages/soothe/src/soothe/ | wc -l  # Expected: ~30-40
grep -r "from soothe_sdk import" packages/soothe-sdk/tests/ | wc -l  # Expected: ~40-50
```

---

## Implementation Phases

### Phase 1: SDK Structure Refactoring (Days 1-3)

**Goal:** Reorganize SDK directory structure without breaking SDK internal imports

#### Step 1.1: Create New Directory Structure

**Create directories:**
```bash
cd packages/soothe-sdk/src/soothe_sdk
mkdir -p plugin ux utils
# Ensure protocols/ client/ exist (already present)
```

**Verify:**
```bash
ls -la packages/soothe-sdk/src/soothe_sdk/
# Expected: plugin/, ux/, utils/, protocols/, client/, types/
```

#### Step 1.2: Move Files - Root to Packages

**Batch 1: Client package**
```bash
# Move config files (will merge later)
mv packages/soothe-sdk/src/soothe_sdk/config_constants.py packages/soothe-sdk/src/soothe_sdk/client/config_constants.py
mv packages/soothe-sdk/src/soothe_sdk/config_types.py packages/soothe-sdk/src/soothe_sdk/client/config_types.py

# Move protocol files
mv packages/soothe-sdk/src/soothe_sdk/protocol.py packages/soothe-sdk/src/soothe_sdk/client/protocol.py
mv packages/soothe-sdk/src/soothe_sdk/protocol_schemas.py packages/soothe-sdk/src/soothe_sdk/client/schemas.py
```

**Batch 2: Plugin package**
```bash
# Move plugin-related files
mv packages/soothe-sdk/src/soothe_sdk/depends.py packages/soothe-sdk/src/soothe_sdk/plugin/depends.py
mv packages/soothe-sdk/src/soothe_sdk/events_registry.py packages/soothe-sdk/src/soothe_sdk/plugin/registry.py
mv packages/soothe-sdk/src/soothe_sdk/progress.py packages/soothe-sdk/src/soothe_sdk/plugin/emit.py

# Move types to plugin
mv packages/soothe-sdk/src/soothe_sdk/types/manifest.py packages/soothe-sdk/src/soothe_sdk/plugin/manifest.py
mv packages/soothe-sdk/src/soothe_sdk/types/context.py packages/soothe-sdk/src/soothe_sdk/plugin/context.py
mv packages/soothe-sdk/src/soothe_sdk/types/health.py packages/soothe-sdk/src/soothe_sdk/plugin/health.py
```

**Batch 3: UX package**
```bash
# Move UX files
mv packages/soothe-sdk/src/soothe_sdk/ux_types.py packages/soothe-sdk/src/soothe_sdk/ux/types.py
mv packages/soothe-sdk/src/soothe_sdk/internal.py packages/soothe-sdk/src/soothe_sdk/ux/internal.py
```

**Batch 4: Utils package**
```bash
# Move utility files
mv packages/soothe-sdk/src/soothe_sdk/logging_utils.py packages/soothe-sdk/src/soothe_sdk/utils/logging.py
mv packages/soothe-sdk/src/soothe_sdk/workspace_types.py packages/soothe-sdk/src/soothe_sdk/utils/workspace.py

# Move utils.py content (will split later)
mv packages/soothe-sdk/src/soothe_sdk/utils.py packages/soothe-sdk/src/soothe_sdk/utils/general.py
```

**Batch 5: Merge decorators**
```bash
# Move decorator files to temporary location for merging
mv packages/soothe-sdk/src/soothe_sdk/decorators/plugin.py packages/soothe-sdk/src/soothe_sdk/plugin/decorator_plugin.py
mv packages/soothe-sdk/src/soothe_sdk/decorators/tool.py packages/soothe-sdk/src/soothe_sdk/plugin/decorator_tool.py
mv packages/soothe-sdk/src/soothe_sdk/decorators/subagent.py packages/soothe-sdk/src/soothe_sdk/plugin/decorator_subagent.py
```

#### Step 1.3: Merge Files

**Merge config files into client/config.py:**
```python
# File: packages/soothe-sdk/src/soothe_sdk/client/config.py
# Combine config_constants.py + config_types.py content

# Read both files
config_constants = Path("packages/soothe-sdk/src/soothe_sdk/client/config_constants.py").read_text()
config_types = Path("packages/soothe-sdk/src/soothe_sdk/client/config_types.py").read_text()

# Merge into single file with proper sections
merged_config = f'''"""Client configuration constants and types.

Merged from config_constants.py + config_types.py (IG-185).
"""

# Constants (from config_constants.py)
{config_constants.split("\"\"\"")[2].strip()}

# Types (from config_types.py)
{config_types.split("\"\"\"")[2].strip()}
'''

# Write merged file
Path("packages/soothe-sdk/src/soothe_sdk/client/config.py").write_text(merged_config)

# Remove old files
rm packages/soothe-sdk/src/soothe_sdk/client/config_constants.py
rm packages/soothe-sdk/src/soothe_sdk/client/config_types.py
```

**Merge decorator files into plugin/decorators.py:**
```python
# File: packages/soothe-sdk/src/soothe_sdk/plugin/decorators.py
# Combine plugin.py, tool.py, subagent.py

# Read all three decorator files
decorator_plugin = Path("packages/soothe-sdk/src/soothe_sdk/plugin/decorator_plugin.py").read_text()
decorator_tool = Path("packages/soothe-sdk/src/soothe_sdk/plugin/decorator_tool.py").read_text()
decorator_subagent = Path("packages/soothe-sdk/src/soothe_sdk/plugin/decorator_subagent.py").read_text()

# Extract imports and content from each
# Merge into single decorators.py file
# Follow pattern: imports first, then @plugin, @tool, @tool_group, @subagent definitions

# Write merged file
# Remove temporary decorator files
```

**Split utils.py into utils/display.py + utils/parsing.py:**
```python
# Read utils/general.py
utils_content = Path("packages/soothe-sdk/src/soothe_sdk/utils/general.py").read_text()

# Extract display-related functions:
display_functions = [
    "format_cli_error",
    "log_preview",
    "convert_and_abbreviate_path",
    "get_tool_display_name"
]

# Extract parsing-related functions:
parsing_functions = [
    "parse_autopilot_goals",
    "_TASK_NAME_RE",
    "resolve_provider_env",
    "is_path_argument"
]

# Create utils/display.py with display functions + imports
# Create utils/parsing.py with parsing functions + imports

# Remove utils/general.py
```

#### Step 1.4: Extract classification.py from verbosity.py

```python
# Extract classify_event_to_tier() from verbosity.py
verbosity_content = Path("packages/soothe-sdk/src/soothe_sdk/verbosity.py").read_text()

# Find classify_event_to_tier function definition
# Extract the function + helper constants (_DOMAIN_DEFAULT_TIER, etc.)

# Create ux/classification.py with the extracted logic
# Update verbosity.py to import from ux/classification.py if needed
# Or remove the function entirely from verbosity.py (move completely)
```

#### Step 1.5: Create Package __init__.py Files

**plugin/__init__.py:**
```python
"""Plugin development API for Soothe."""

from soothe_sdk.plugin.decorators import plugin, tool, tool_group, subagent
from soothe_sdk.plugin.manifest import PluginManifest as Manifest
from soothe_sdk.plugin.context import PluginContext as Context, SootheConfigProtocol
from soothe_sdk.plugin.health import PluginHealth as Health
from soothe_sdk.plugin.depends import library as Depends
from soothe_sdk.plugin.registry import register_event
from soothe_sdk.plugin.emit import emit_progress, set_stream_writer

__all__ = [
    "plugin", "tool", "tool_group", "subagent",
    "Manifest", "Context", "SootheConfigProtocol", "Health",
    "Depends", "register_event", "emit_progress", "set_stream_writer",
]
```

**client/__init__.py:**
```python
"""WebSocket client utilities for connecting to Soothe daemon."""

from soothe_sdk.client.websocket import WebSocketClient, VerbosityLevel
from soothe_sdk.client.session import (
    bootstrap_thread_session,
    connect_websocket_with_retries,
)
from soothe_sdk.client.helpers import (
    websocket_url_from_config,
    check_daemon_status,
    is_daemon_live,
    request_daemon_shutdown,
    fetch_skills_catalog,
    fetch_config_section,
)

__all__ = [
    "WebSocketClient", "VerbosityLevel",
    "bootstrap_thread_session", "connect_websocket_with_retries",
    "websocket_url_from_config", "check_daemon_status",
    "is_daemon_live", "request_daemon_shutdown",
    "fetch_skills_catalog", "fetch_config_section",
]
```

**ux/__init__.py:**
```python
"""Display and UX concerns for event processing."""

from soothe_sdk.ux.types import ESSENTIAL_EVENT_TYPES
from soothe_sdk.ux.internal import strip_internal_tags, INTERNAL_JSON_KEYS
from soothe_sdk.ux.classification import classify_event_to_tier

__all__ = [
    "ESSENTIAL_EVENT_TYPES",
    "strip_internal_tags",
    "INTERNAL_JSON_KEYS",
    "classify_event_to_tier",
]
```

**utils/__init__.py:**
```python
"""Shared utilities for SDK, CLI, and daemon."""

from soothe_sdk.utils.logging import (
    setup_logging,
    GlobalInputHistory,
    VERBOSITY_TO_LOG_LEVEL,
)
from soothe_sdk.utils.display import (
    format_cli_error,
    log_preview,
    convert_and_abbreviate_path,
    get_tool_display_name,
)
from soothe_sdk.utils.parsing import (
    parse_autopilot_goals,
    _TASK_NAME_RE,
    resolve_provider_env,
)
from soothe_sdk.utils.workspace import INVALID_WORKSPACE_DIRS, is_path_argument

__all__ = [
    "setup_logging", "GlobalInputHistory", "VERBOSITY_TO_LOG_LEVEL",
    "format_cli_error", "log_preview", "convert_and_abbreviate_path",
    "get_tool_display_name", "parse_autopilot_goals", "_TASK_NAME_RE",
    "resolve_provider_env", "INVALID_WORKSPACE_DIRS", "is_path_argument",
]
```

#### Step 1.6: Update Root __init__.py

```python
# File: packages/soothe-sdk/src/soothe_sdk/__init__.py

"""Soothe SDK - Minimal __init__.py matching langchain-core pattern."""

__version__ = "0.4.0"  # Version bump (breaking change)
__soothe_required_version__ = ">=0.4.0,<1.0.0"

# No re-exports - use package imports:
# from soothe_sdk.events import SootheEvent
# from soothe_sdk.plugin import plugin, tool
# from soothe_sdk.client import WebSocketClient
# from soothe_sdk.protocols import PersistStore
# from soothe_sdk.utils import setup_logging
```

#### Step 1.7: Deprecate types/ Package

```python
# File: packages/soothe-sdk/src/soothe_sdk/types/__init__.py

"""Types package - DEPRECATED.

All types have been moved to their respective packages:
- PluginManifest → soothe_sdk.plugin.Manifest
- PluginContext → soothe_sdk.plugin.Context
- PluginHealth → soothe_sdk.plugin.Health

This package is empty and will be removed in future versions.
"""

# No exports
__all__ = []
```

#### Step 1.8: Update SDK Internal Imports

**Files to update (within SDK):**
1. `plugin/decorators.py` - imports from types → plugin
2. `plugin/registry.py` - imports from events, verbosity
3. `ux/classification.py` - imports from verbosity
4. `client/helpers.py` - imports from websocket

**Example:**
```python
# Before: plugin/decorators.py imports
from soothe_sdk.types.manifest import PluginManifest

# After: plugin/decorators.py imports
from soothe_sdk.plugin.manifest import PluginManifest as Manifest
```

#### Step 1.9: Run SDK Tests

```bash
cd packages/soothe-sdk
pytest tests/ -v

# Expected: All SDK unit tests pass
# Fix any import errors within SDK itself
```

**Phase 1 Verification:**
```bash
# Check file count
find packages/soothe-sdk/src/soothe_sdk -name "*.py" -not -path "*__pycache__" | wc -l
# Expected: 27 files (reduced from 32)

# Check structure
tree packages/soothe-sdk/src/soothe_sdk -I '__pycache__'
# Expected: plugin/, ux/, utils/, client/, protocols/, types/ (deprecated), root files (events, exceptions, verbosity)
```

---

### Phase 2: soothe-cli Imports Update (Day 4)

**Goal:** Update all CLI import statements to use new package paths

#### Step 2.1: Find All CLI Imports

```bash
# Generate list of files needing updates
grep -r "from soothe_sdk import" packages/soothe-cli/src/ --include="*.py" > /tmp/cli_imports.txt

# Count imports
wc -l /tmp/cli_imports.txt
# Expected: ~20-25 lines
```

#### Step 2.2: Update Imports - Batch Script

**Create automated update script:**
```python
#!/usr/bin/env python3
"""Automated import path updates for soothe-cli package."""

import re
from pathlib import Path

# Import mapping (from RFC-610)
IMPORT_MAPPING = {
    "from soothe_sdk import plugin": "from soothe_sdk.plugin import plugin",
    "from soothe_sdk import tool": "from soothe_sdk.plugin import tool",
    "from soothe_sdk import subagent": "from soothe_sdk.plugin import subagent",
    "from soothe_sdk import PluginManifest": "from soothe_sdk.plugin import Manifest",
    "from soothe_sdk import PluginContext": "from soothe_sdk.plugin import Context",
    "from soothe_sdk import WebSocketClient": "from soothe_sdk.client import WebSocketClient",
    "from soothe_sdk import VerbosityLevel": "from soothe_sdk.client import VerbosityLevel",
    "from soothe_sdk import bootstrap_thread_session": "from soothe_sdk.client import bootstrap_thread_session",
    "from soothe_sdk import encode": "from soothe_sdk.client.protocol import encode",
    "from soothe_sdk import decode": "from soothe_sdk.client.protocol import decode",
    "from soothe_sdk import SOOTHE_HOME": "from soothe_sdk.client.config import SOOTHE_HOME",
    "from soothe_sdk import DEFAULT_EXECUTE_TIMEOUT": "from soothe_sdk.client.config import DEFAULT_EXECUTE_TIMEOUT",
    "from soothe_sdk import setup_logging": "from soothe_sdk.utils import setup_logging",
    "from soothe_sdk import GlobalInputHistory": "from soothe_sdk.utils import GlobalInputHistory",
    "from soothe_sdk import format_cli_error": "from soothe_sdk.utils import format_cli_error",
    "from soothe_sdk import log_preview": "from soothe_sdk.utils import log_preview",
    "from soothe_sdk import ESSENTIAL_EVENT_TYPES": "from soothe_sdk.ux import ESSENTIAL_EVENT_TYPES",
    # Core imports (no change):
    # "from soothe_sdk.events import ...": unchanged
    # "from soothe_sdk.exceptions import ...": unchanged
    # "from soothe_sdk.verbosity import ...": unchanged
}

def update_file(file_path: Path):
    """Update import statements in a file."""
    content = file_path.read_text()
    original = content
    
    for old_import, new_import in IMPORT_MAPPING.items():
        content = content.replace(old_import, new_import)
    
    if content != original:
        file_path.write_text(content)
        print(f"✓ Updated: {file_path}")
        return True
    return False

# Process all CLI files
cli_root = Path("packages/soothe-cli/src")
updated_count = 0

for py_file in cli_root.rglob("*.py"):
    if update_file(py_file):
        updated_count += 1

print(f"\n✓ Updated {updated_count} files in soothe-cli")
```

**Run script:**
```bash
python3 /tmp/update_cli_imports.py
# Expected: ~10-15 files updated
```

#### Step 2.3: Manual Verification

**Check critical files:**
```bash
# Verify cli_config.py
grep "from soothe_sdk" packages/soothe-cli/src/soothe_cli/config/cli_config.py

# Expected: from soothe_sdk.client.config import ...
# Expected: from soothe_sdk.verbosity import ...

# Verify TUI files
grep "from soothe_sdk" packages/soothe-cli/src/soothe_cli/tui/*.py

# Expected: from soothe_sdk.client import WebSocketClient
# Expected: from soothe_sdk.utils import ...
```

#### Step 2.4: Run CLI Tests

```bash
cd packages/soothe-cli
pytest tests/ -v

# Expected: All CLI tests pass
# Fix any import errors
```

#### Step 2.5: Integration Test

```bash
# Test CLI commands
soothe --help
soothe thread list

# Test TUI launch (if daemon running)
soothe

# Test headless mode
soothe -p "test query"

# Expected: All commands work without import errors
```

---

### Phase 3: soothe (daemon) Imports Update (Day 5)

**Goal:** Update all daemon import statements (~30-40 in 20-30 files)

#### Step 3.1: Find All Daemon Imports

```bash
# Generate list
grep -r "from soothe_sdk import" packages/soothe/src/soothe/ --include="*.py" > /tmp/daemon_imports.txt

# Count
wc -l /tmp/daemon_imports.txt
# Expected: ~30-40 lines
```

#### Step 3.2: Automated Update Script

**Use same mapping as Phase 2, different target directory:**
```python
#!/usr/bin/env python3
"""Automated import updates for soothe daemon package."""

# Same IMPORT_MAPPING as Phase 2
# ...

# Process all daemon files
daemon_root = Path("packages/soothe/src/soothe")
updated_count = 0

for py_file in daemon_root.rglob("*.py"):
    if update_file(py_file):
        updated_count += 1

print(f"\n✓ Updated {updated_count} files in soothe daemon")
```

**Run script:**
```bash
python3 /tmp/update_daemon_imports.py
# Expected: ~20-30 files updated
```

#### Step 3.3: Manual Verification - Critical Files

**Check core modules:**
```bash
# core/agent.py - plugin imports
grep "from soothe_sdk" packages/soothe/src/soothe/core/agent.py
# Expected: from soothe_sdk.plugin import plugin, tool, Manifest

# core/runner.py - event imports
grep "from soothe_sdk" packages/soothe/src/soothe/core/runner.py
# Expected: from soothe_sdk.events import ... (unchanged)

# backends/policy/config_driven.py - protocol imports
grep "from soothe_sdk" packages/soothe/src/soothe/backends/policy/config_driven.py
# Expected: from soothe_sdk.protocols import PolicyProtocol
```

#### Step 3.4: Run Daemon Tests

```bash
cd packages/soothe
pytest tests/ -v

# Expected: All daemon tests pass
# Fix any import errors
```

#### Step 3.5: Integration Test

```bash
# Test daemon commands
soothe-daemon start
soothe-daemon status
soothe-daemon doctor

# Expected: All commands work
# Test daemon + CLI connection
soothe -p "test query"

# Expected: Full stack works
```

---

### Phase 4: Full Test Suite (Day 6)

**Goal:** Verify all 900+ tests pass with new structure

#### Step 4.1: Run Verification Script

```bash
./scripts/verify_finally.sh

# Expected results:
# - Code formatting: PASS
# - Linting (zero errors): PASS
# - Unit tests (900+): PASS
```

**If tests fail:**
```bash
# Identify failures
pytest tests/ -v --tb=short

# Fix import paths in failing tests
# Re-run verification
```

#### Step 4.2: Import Timing Benchmark

```bash
# Measure import time before and after
python3 << 'EOF'
import time
import sys

# Test old import pattern (if available)
start = time.time()
# Old: import soothe_sdk (would load all 50+ modules)
# Can't test old directly since structure changed

# Test new import pattern
start_new = time.time()
import soothe_sdk  # Minimal __init__.py
end_new = time.time()

print(f"New import time: {end_new - start_new:.4f}s")
print(f"Minimal __init__.py loads faster (only version)")
EOF
```

**Expected:** Import time significantly faster (minimal __init__.py)

#### Step 4.3: Circular Import Check

```bash
python3 << 'EOF'
import sys
import importlib.util
from pathlib import Path

sdk_packages = [
    "soothe_sdk.plugin",
    "soothe_sdk.client",
    "soothe_sdk.ux",
    "soothe_sdk.utils",
    "soothe_sdk.protocols",
]

print("Testing package imports (circular import check):")

for package in sdk_packages:
    try:
        spec = importlib.util.find_spec(package)
        if spec:
            print(f"  ✓ {package} - imports successfully")
        else:
            print(f"  ✗ {package} - not found")
    except ImportError as e:
        print(f"  ✗ {package} - circular import: {e}")

print("\n✓ No circular imports detected")
EOF
```

#### Step 4.4: Package Isolation Tests

```bash
# Test each package can import independently
python3 -c "from soothe_sdk.events import SootheEvent; print('✓ events')"
python3 -c "from soothe_sdk.plugin import plugin; print('✓ plugin')"
python3 -c "from soothe_sdk.client import WebSocketClient; print('✓ client')"
python3 -c "from soothe_sdk.protocols import PersistStore; print('✓ protocols')"
python3 -c "from soothe_sdk.utils import setup_logging; print('✓ utils')"
python3 -c "from soothe_sdk.ux import ESSENTIAL_EVENT_TYPES; print('✓ ux')"

# Expected: All succeed independently
```

#### Step 4.5: Import Completeness Check

```bash
# Verify ALL imports updated (no old patterns remaining)
grep -r "from soothe_sdk import plugin" packages/ | grep -v "__pycache__" || echo "✓ No old plugin imports"
grep -r "from soothe_sdk import WebSocketClient" packages/ | grep -v "__pycache__" || echo "✓ No old WebSocketClient imports"
grep -r "from soothe_sdk import setup_logging" packages/ | grep -v "__pycache__" || echo "✓ No old setup_logging imports"

# Expected: No old pattern matches (all updated)
```

---

### Phase 5: Documentation Update (Day 7)

**Goal:** Update all documentation with new import patterns

#### Step 5.1: Update CLI Architecture Doc

**File:** `docs/cli-entry-points-architecture.md`

```markdown
## SDK Package Structure (v0.4.0)

soothe-sdk follows langchain-core patterns with purpose packages:

### Import Pattern

```python
# Plugin API
from soothe_sdk.plugin import plugin, tool, Manifest

# Client utilities
from soothe_sdk.client import WebSocketClient
from soothe_sdk.client.protocol import encode, decode

# Core concepts (root level)
from soothe_sdk.events import SootheEvent
from soothe_sdk.exceptions import PluginError
from soothe_sdk.verbosity import VerbosityTier

# Utilities
from soothe_sdk.utils import setup_logging, format_cli_error

# Protocols
from soothe_sdk.protocols import PersistStore, PolicyProtocol
```

### Package Structure

- **plugin/** - Plugin development API (@plugin, @tool, @subagent, Manifest, etc.)
- **client/** - WebSocket client utilities (WebSocketClient, helpers, wire protocol)
- **ux/** - Display/UX concerns (ESSENTIAL_EVENT_TYPES, classification)
- **utils/** - Shared utilities (logging, display, parsing, workspace)
- **protocols/** - Protocol definitions (PersistStore, PolicyProtocol, VectorStoreProtocol)
- **Root files** - Core concepts (events.py, exceptions.py, verbosity.py)

**Breaking change:** v0.4.0 requires package-level imports.
```

#### Step 5.2: Update Migration Guide

**File:** `docs/migration-guide-v0.3.md`

**Add section:**
```markdown
## v0.4.0 Breaking Changes: SDK Module Structure

**Release date:** 2026-04-XX  
**Breaking change:** All SDK import paths changed

### Quick Migration

Replace old imports with new package-level imports:

```python
# Before (v0.3.x)
from soothe_sdk import plugin, tool, WebSocketClient

# After (v0.4.0)
from soothe_sdk.plugin import plugin, tool
from soothe_sdk.client import WebSocketClient
```

### Complete Import Mapping

[Insert 50-row mapping table from RFC-610]

### Migration Steps

1. Update all `from soothe_sdk import` statements
2. Use package-level imports: `from soothe_sdk.<package> import <item>`
3. Core imports unchanged: events, exceptions, verbosity remain at root
4. Version bump: soothe-sdk >= v0.4.0

**No backward compatibility** - update imports before upgrading.
```

#### Step 5.3: Update CLAUDE.md

**File:** `CLAUDE.md`

**Update sections:**
```markdown
## SDK Module Structure

soothe-sdk follows langchain-core patterns (v0.4.0+):

### Quick Import Guide

```python
# Plugin development
from soothe_sdk.plugin import plugin, tool, subagent, Manifest

# Client utilities
from soothe_sdk.client import WebSocketClient, bootstrap_thread_session

# Core (unchanged)
from soothe_sdk.events import SootheEvent
from soothe_sdk.exceptions import PluginError
from soothe_sdk.verbosity import VerbosityTier

# Utilities
from soothe_sdk.utils import setup_logging

# Protocols
from soothe_sdk.protocols import PersistStore
```

### Package Organization

- **plugin/** - All plugin API (decorators + types)
- **client/** - WebSocket client + helpers
- **ux/** - Display/UX types
- **utils/** - Logging, formatting, parsing
- **protocols/** - Stable protocol interfaces
- **Root** - Events, exceptions, verbosity only

**Note:** v0.4.0 breaking change - use package imports.
```

#### Step 5.4: Update SDK README

**File:** `packages/soothe-sdk/README.md`

```markdown
# soothe-sdk

SDK for building Soothe plugins and client utilities.

## Package Structure (v0.4.0)

Follows langchain-core patterns with purpose packages.

### Import Examples

```python
# Plugin API
from soothe_sdk.plugin import plugin, tool, Manifest

# Client
from soothe_sdk.client import WebSocketClient

# Core
from soothe_sdk.events import SootheEvent

# Utils
from soothe_sdk.utils import setup_logging
```

## Breaking Changes

**v0.4.0:** All imports changed to package-level. See migration guide.
```

#### Step 5.5: Update Code Examples in Docs

**Find all markdown files with import examples:**
```bash
grep -r "from soothe_sdk import" docs/ --include="*.md" > /tmp/doc_imports.txt

# Update each file manually or with script
# Focus on: RFCs, user guides, implementation guides
```

---

### Phase 6: Version Bump and Release (Week 2)

**Goal:** Version bump all packages and publish migration guide

#### Step 6.1: Update pyproject.toml Versions

**soothe-sdk:**
```toml
# packages/soothe-sdk/pyproject.toml
version = "0.4.0"  # Breaking change
```

**soothe-cli:**
```toml
# packages/soothe-cli/pyproject.toml
version = "0.2.0"
dependencies = ["soothe-sdk>=0.4.0,<1.0.0"]
```

**soothe (daemon):**
```toml
# packages/soothe/pyproject.toml
version = "0.4.0"
dependencies = ["soothe-sdk>=0.4.0,<1.0.0"]
```

#### Step 6.2: Update Version in __init__.py

**Already updated in Phase 1:**
```python
# packages/soothe-sdk/src/soothe_sdk/__init__.py
__version__ = "0.4.0"
__soothe_required_version__ = ">=0.4.0,<1.0.0"
```

#### Step 6.3: Create Release Notes

**File:** `RELEASE_NOTES.md`

```markdown
# v0.4.0 Release Notes - SDK Module Structure Refactoring

**Release date:** 2026-04-XX  
**Breaking change:** Yes - all import paths changed

## Summary

Refactored soothe-sdk module structure to align with langchain-core patterns:
- 15 root files → 3 core files (events, exceptions, verbosity)
- Purpose packages: plugin/, client/, ux/, utils/, protocols/
- Minimal __init__.py (version-only)
- 5 files eliminated via merging

## Breaking Changes

**ALL import paths changed.** No backward compatibility provided.

### Migration Required

Update all import statements before upgrading:

```python
# Old (v0.3.x)
from soothe_sdk import plugin, WebSocketClient, setup_logging

# New (v0.4.0)
from soothe_sdk.plugin import plugin
from soothe_sdk.client import WebSocketClient
from soothe_sdk.utils import setup_logging
```

See [Migration Guide](docs/migration-guide-v0.3.md#v0.4.0) for complete mapping table.

## Benefits

- Matches langchain/deepagents patterns
- Clear purpose boundaries
- Better organization
- Faster import (minimal __init__.py)
- Easier navigation

## Action Required

**Update all imports before installing v0.4.0.**

1. Review migration guide
2. Update import statements
3. Test with new imports
4. Upgrade to v0.4.0

## Third-Party Plugin Authors

Update your plugin imports:

```python
from soothe_sdk.plugin import plugin, tool, Manifest
from soothe_sdk.events import SootheEvent  # unchanged
from soothe_sdk.verbosity import VerbosityTier  # unchanged
```
```

#### Step 6.4: Publish Migration Guide

```bash
# Ensure migration guide is complete
cat docs/migration-guide-v0.3.md | grep "v0.4.0"

# Expected: Complete v0.4.0 section with mapping table
```

#### Step 6.5: Final Verification

```bash
# Run full verification one last time
./scripts/verify_finally.sh

# Expected: All tests pass, zero linting errors

# Check version
python3 -c "import soothe_sdk; print(soothe_sdk.__version__)"
# Expected: 0.4.0
```

---

## Post-Implementation Verification

### Success Criteria Checklist

**Run after all phases complete:**

```bash
#!/bin/bash
echo "=== IG-185 Success Criteria Verification ==="

# 1. All tests pass
echo "1. Running tests..."
./scripts/verify_finally.sh && echo "  ✓ Tests pass" || echo "  ✗ Tests fail"

# 2. No circular imports
echo "2. Checking circular imports..."
python3 -c "import soothe_sdk.plugin; import soothe_sdk.client; import soothe_sdk.utils; print('  ✓ No circular imports')" || echo "  ✗ Circular imports detected"

# 3. CLI imports updated
echo "3. Checking CLI imports..."
CLI_COUNT=$(grep -r "from soothe_sdk import plugin" packages/soothe-cli/src/ --include="*.py" | wc -l)
[ "$CLI_COUNT" -eq 0 ] && echo "  ✓ CLI imports updated" || echo "  ✗ Old CLI imports found"

# 4. Daemon imports updated
echo "4. Checking daemon imports..."
DAEMON_COUNT=$(grep -r "from soothe_sdk import WebSocketClient" packages/soothe/src/soothe/ --include="*.py" | wc -l)
[ "$DAEMON_COUNT" -eq 0 ] && echo "  ✓ Daemon imports updated" || echo "  ✗ Old daemon imports found"

# 5. File count reduced
echo "5. Checking file count..."
FILE_COUNT=$(find packages/soothe-sdk/src/soothe_sdk -name "*.py" -not -path "*__pycache__" | wc -l)
[ "$FILE_COUNT" -eq 27 ] && echo "  ✓ File count: 27 (reduced from 32)" || echo "  ✗ File count: $FILE_COUNT (expected 27)"

# 6. Version bumped
echo "6. Checking version..."
VERSION=$(python3 -c "import soothe_sdk; print(soothe_sdk.__version__)")
[ "$VERSION" = "0.4.0" ] && echo "  ✓ Version: 0.4.0" || echo "  ✗ Version: $VERSION"

# 7. Docs updated
echo "7. Checking documentation..."
[ -f "docs/migration-guide-v0.3.md" ] && grep -q "v0.4.0" docs/migration-guide-v0.3.md && echo "  ✓ Migration guide updated" || echo "  ✗ Migration guide missing"

# 8. Minimal __init__.py
echo "8. Checking __init__.py..."
INIT_LINES=$(wc -l < packages/soothe-sdk/src/soothe_sdk/__init__.py)
[ "$INIT_LINES" -lt 20 ] && echo "  ✓ Minimal __init__.py ($INIT_LINES lines)" || echo "  ✗ __init__.py too large ($INIT_LINES lines)"

# 9. Package structure
echo "9. Checking package structure..."
[ -d "packages/soothe-sdk/src/soothe_sdk/plugin" ] && echo "  ✓ plugin/ package exists" || echo "  ✗ plugin/ missing"
[ -d "packages/soothe-sdk/src/soothe_sdk/client" ] && echo "  ✓ client/ package exists" || echo "  ✗ client/ missing"
[ -d "packages/soothe-sdk/src/soothe_sdk/ux" ] && echo "  ✓ ux/ package exists" || echo "  ✗ ux/ missing"
[ -d "packages/soothe-sdk/src/soothe_sdk/utils" ] && echo "  ✓ utils/ package exists" || echo "  ✗ utils/ missing"

# 10. Import timing
echo "10. Checking import performance..."
python3 << 'EOF'
import time
start = time.time()
import soothe_sdk
end = time.time()
elapsed = end - start
if elapsed < 0.1:
    print(f"  ✓ Import time: {elapsed:.4f}s (fast)")
else:
    print(f"  ⚠ Import time: {elapsed:.4f}s (check optimization)")
EOF

echo "=== Verification Complete ==="
```

**Run verification:**
```bash
chmod +x /tmp/verify_ig185.sh
/tmp/verify_ig185.sh
```

**Expected:** All 10 criteria pass ✓

---

## Rollback Plan

**If critical issues discovered:**

### Emergency Rollback Procedure

**Step 1: Revert file moves**
```bash
# Restore original structure from git
cd packages/soothe-sdk
git checkout HEAD -- src/soothe_sdk/

# Expected: Original 32 files restored
```

**Step 2: Revert import updates**
```bash
# Revert CLI imports
cd packages/soothe-cli
git checkout HEAD -- src/

# Revert daemon imports
cd packages/soothe
git checkout HEAD -- src/
```

**Step 3: Revert version bump**
```bash
# Restore v0.3.0
git checkout HEAD -- packages/*/pyproject.toml
```

**Step 4: Run tests**
```bash
./scripts/verify_finally.sh

# Expected: Tests pass with original structure
```

**Step 5: Document rollback**
```markdown
# IG-185 Rollback Log

**Date:** YYYY-MM-DD
**Reason:** [Describe critical issue]
**Rollback steps:** Executed git checkout
**Status:** Rolled back to v0.3.0
**Next action:** [Plan to fix issue before retry]
```

---

## Dependencies and Coordination

### Blocked By

- IG-173 (CLI-Daemon Split) - ✅ Complete (SDK v0.2.0 exists)
- IG-174 (CLI Import Violations) - ✅ Complete (SDK exports established)
- IG-175 (WebSocket Migration) - ✅ Complete (Client package exists)

### Blocks

- None (standalone refactoring)

### Coordination Required

- **Third-party plugin authors** - communicate breaking change via migration guide
- **soothe-cli development** - coordinate CLI import updates (Phase 2)
- **soothe (daemon) development** - coordinate daemon import updates (Phase 3)

---

## Metrics and Impact

### Code Changes

- **Files moved:** 15 root → packages
- **Files merged:** 4 (config, decorators)
- **Files split:** 1 (utils.py → display.py + parsing.py)
- **Files eliminated:** 5 (via merging)
- **Import statements updated:** ~110-130 across 45-65 files

### Package Size

- **Before:** 32 files (15 root + 17 subpackages)
- **After:** 27 files (3 root + 24 subpackages)
- **__init__.py:** 197 lines → 10 lines (minimal)

### Breaking Impact

- **Internal packages:** CLI (~20 imports), daemon (~30 imports)
- **External:** All third-party plugins
- **Mitigation:** Complete mapping table + migration guide

---

## Testing Requirements

### Unit Tests

- soothe-sdk: All tests pass (config, decorators, events, etc.)
- soothe-cli: All tests pass (TUI, headless, commands)
- soothe: All 900+ tests pass (core, protocols, backends, tools, subagents)

### Integration Tests

- CLI → daemon WebSocket connection
- Plugin loading with new structure
- Daemon startup + health checks
- Full stack: CLI + daemon + agent execution

### Performance Tests

- Import timing (minimal __init__.py benchmark)
- Package isolation (each package imports independently)
- Circular import detection

---

## Documentation Deliverables

1. ✅ RFC-610 (SDK Module Structure Refactoring)
2. ✅ IG-185 (this implementation guide)
3. 🟡 Migration guide v0.4.0 section
4. 🟡 CLI architecture doc updates
5. 🟡 CLAUDE.md import pattern updates
6. 🟡 SDK README updates
7. 🟡 Release notes

---

## Timeline Summary

| Phase | Duration | Key Activities |
|-------|----------|----------------|
| 1 | Days 1-3 | SDK structure reorganization |
| 2 | Day 4 | CLI imports update (~20-25) |
| 3 | Day 5 | Daemon imports update (~30-40) |
| 4 | Day 6 | Full test suite + verification |
| 5 | Day 7 | Documentation updates |
| 6 | Week 2 | Version bump + release |

**Total:** 1-2 weeks (no backward compatibility layer)

---

## Risks and Mitigation

**See RFC-610 for full risk analysis. Key risks:**

1. **Third-party plugins breaking** - Mitigate with complete migration guide
2. **Import errors during migration** - Mitigate with batch-by-batch execution + tests
3. **Circular imports introduced** - Mitigate with import graph analysis + package isolation tests
4. **Missed imports** - Mitigate with grep + linting + 900+ test coverage
5. **Performance regression** - Mitigate with import timing benchmark

---

## Success Indicators

✅ All 900+ tests pass  
✅ No circular imports  
✅ CLI imports updated (~20-25 statements)  
✅ Daemon imports updated (~30-40 statements)  
✅ Documentation updated  
✅ Version bumped to v0.4.0  
✅ Minimal __init__.py (< 20 lines)  
✅ Import time improved  
✅ Package structure verified  
✅ File count reduced (32 → 27)  

---

**Implementation Status:** 🟡 Pending execution  
**Next Action:** Execute Phase 1 (SDK structure refactoring)  
**Estimated Start:** Upon approval  
**Target Completion:** 1-2 weeks from start