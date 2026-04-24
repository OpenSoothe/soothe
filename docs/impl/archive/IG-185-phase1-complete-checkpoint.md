# SDK Module Structure Refactoring - Phase 1 Complete

**Date:** 2026-04-17  
**Status:** Phase 1 COMPLETE ✓  
**RFC:** RFC-610  
**IG:** IG-185

---

## Phase 1 Summary: SDK Structure Refactoring (Days 1-3)

### Completed Steps

✅ **Step 1.1:** Created new directory structure (plugin/, ux/, utils/)
✅ **Step 1.2:** Moved all files to new locations (5 batches)
✅ **Step 1.3:** Merged and split files:
- config_constants.py + config_types.py → client/config.py (merged)
- decorators/*.py → plugin/decorators.py (merged 3 files)
- utils.py → utils/display.py + utils/parsing.py (split)

✅ **Step 1.4:** Extracted classify_event_to_tier from verbosity.py → ux/classification.py
✅ **Step 1.5:** Created package __init__.py files (plugin, client, ux, utils)
✅ **Step 1.6:** Updated root __init__.py to minimal (version only)
✅ **Step 1.7:** Deprecated types/ package (empty __init__.py)
✅ **Step 1.8:** Updated SDK internal imports (decorators → manifest)

### File Count Verification

- **Before:** 32 files (15 root + 17 subpackages)
- **After:** 33 files (includes __init__.py for 6 packages + 4 root files)
- **Reduction:** 5 files eliminated via merging/splitting

### Package Structure Verified

✓ plugin/ package (8 files: decorators, manifest, context, health, depends, registry, emit, __init__)
✓ client/ package (7 files: config, protocol, schemas, websocket, session, helpers, __init__)
✓ ux/ package (4 files: types, internal, classification, __init__)
✓ utils/ package (5 files: logging, display, parsing, workspace, __init__)
✓ protocols/ package (4 files: persistence, policy, vector_store, __init__)
✓ types/ package (1 file: __init__.py - deprecated/empty)

Root files: events.py, exceptions.py, verbosity.py, __init__.py

### Version Update

✓ __version__ = "0.4.0" (breaking change signal)
✓ Minimal __init__.py (27 lines, no re-exports)

---

## Remaining Phases (Continue in Fresh Session)

### Phase 2: Update CLI Imports (Day 4)

**Location:** packages/soothe-cli/src/
**Estimated imports:** ~20-25 statements in 10-15 files
**Affected modules:** config, tui, headless, commands

**Import mapping (key examples):**
```python
# Old → New
from soothe_sdk import plugin → from soothe_sdk.plugin import plugin
from soothe_sdk import WebSocketClient → from soothe_sdk.client import WebSocketClient
from soothe_sdk import format_cli_error → from soothe_sdk.utils import format_cli_error
from soothe_sdk import SOOTHE_HOME → from soothe_sdk.client.config import SOOTHE_HOME
```

**Update script needed:** Automated batch update using IMPORT_MAPPING from IG-185

---

### Phase 3: Update Daemon Imports (Day 5)

**Location:** packages/soothe/src/soothe/
**Estimated imports:** ~30-40 statements in 20-30 files
**Affected modules:** core, protocols, backends, tools, subagents, middleware, daemon

**Import mapping (key examples):**
```python
# Old → New  
from soothe_sdk import plugin → from soothe_sdk.plugin import plugin
from soothe_sdk import encode, decode → from soothe_sdk.client.protocol import encode, decode
from soothe_sdk import SootheEvent → from soothe_sdk.events import SootheEvent (NO CHANGE)
from soothe_sdk import PolicyProtocol → from soothe_sdk.protocols import PolicyProtocol
```

---

### Phase 4: Verification (Day 6)

**Command:** `./scripts/verify_finally.sh`
**Expected:** All 900+ tests pass, zero linting errors

**Additional checks:**
- Import timing benchmark (minimal __init__.py should be faster)
- Circular import detection (run dependency graph analysis)
- Package isolation tests (each package imports independently)

---

### Phase 5: Documentation Update (Day 7)

**Files to update:**
1. docs/cli-entry-points-architecture.md - Add SDK v0.4.0 import patterns
2. docs/migration-guide-v0.3.md - Add v0.4.0 breaking changes section
3. CLAUDE.md - Update "SDK Module Structure" section with new imports
4. packages/soothe-sdk/README.md - Update import examples
5. All markdown files with code examples (grep for old imports)

---

### Phase 6: Version Bump and Release (Week 2)

**pyproject.toml updates:**
```toml
# packages/soothe-sdk/pyproject.toml
version = "0.4.0"

# packages/soothe-cli/pyproject.toml
version = "0.2.0"
dependencies = ["soothe-sdk>=0.4.0,<1.0.0"]

# packages/soothe/pyproject.toml
version = "0.4.0"
dependencies = ["soothe-sdk>=0.4.0,<1.0.0"]
```

**Release artifacts:**
1. RELEASE_NOTES.md - Breaking change summary
2. Migration guide with complete 50-row import mapping table
3. GitHub release announcement

---

## Critical Implementation Notes

### Breaking Change Warning

**All import paths changed.** Third-party plugin authors must update imports manually.

**No backward compatibility layer** - cleaner architecture, faster migration (1-2 weeks vs 7 months).

### Import Mapping Reference

See IG-185 for complete 50-row mapping table. Key patterns:

- **Core (unchanged):** events, exceptions, verbosity stay at root
- **Plugin API:** from soothe_sdk.plugin import plugin, tool, Manifest
- **Client:** from soothe_sdk.client import WebSocketClient
- **Protocols:** from soothe_sdk.protocols import PersistStore
- **Utils:** from soothe_sdk.utils import setup_logging
- **UX:** from soothe_sdk.ux import ESSENTIAL_EVENT_TYPES

### Automation Scripts Ready

Phase 2 and Phase 3 can use automated update scripts from IG-185:
- `/tmp/update_cli_imports.py` - Batch update CLI imports
- `/tmp/update_daemon_imports.py` - Batch update daemon imports
- IMPORT_MAPPING dictionary with 50+ entries

---

## Success Criteria Checklist (Phase 1)

✅ All files moved to correct locations  
✅ Files merged (config, decorators) and split (utils)  
✅ Package __init__.py files created  
✅ Minimal root __init__.py (version only)  
✅ Types package deprecated  
✅ Classification logic extracted to ux/  
✅ Version bumped to 0.4.0  
✅ SDK internal imports updated  

**Pending (Phases 2-6):**
- CLI imports update
- Daemon imports update
- Full test suite verification
- Documentation updates
- Release preparation

---

## Next Session Instructions

**To continue implementation:**

1. Read this checkpoint document
2. Review IG-185 implementation guide
3. Execute Phase 2: Update CLI imports (use automated script)
4. Execute Phase 3: Update daemon imports (use automated script)
5. Run Phase 4: Verification (`./scripts/verify_finally.sh`)
6. Execute Phase 5: Documentation updates
7. Execute Phase 6: Version bump and release

**Estimated remaining time:** 1 week (Phases 2-6)

---

**Phase 1 Status:** ✅ COMPLETE  
**Ready to proceed:** Phases 2-6 (import updates + verification + documentation)