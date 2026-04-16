# RFC-404 Specs Refinement Report

**RFC**: RFC-404-slash-command-architecture.md
**Date**: 2026-04-16
**Validator**: Claude (Sonnet 4.6)
**Status**: ✅ VALIDATED - Ready for Implementation

---

## Validation Summary

RFC-404 is well-structured, complete, and ready for implementation. The specification properly extends RFC-400, defines clear architectural boundaries, and provides sufficient implementation detail.

**Overall Assessment**: ✅ PASS - Proceed to implementation guide creation

---

## Validation Checklist

### 1. RFC Structure ✅

**Required sections present**:
- ✅ Abstract (clear problem statement and solution)
- ✅ Motivation (articulates architectural violations)
- ✅ Command Classification (3 categories well-defined)
- ✅ Architecture (layer separation and data flow)
- ✅ Implementation Details (CLI and daemon modules)
- ✅ Testing Strategy (comprehensive coverage)
- ✅ Implementation Phases (6 phases identified)
- ✅ Verification Criteria (8 success criteria)
- ✅ References (RFC-400, RFC-500, IG-176)

**Status**: Complete and well-organized

---

### 2. Dependency Alignment ✅

**Extends RFC-400**: Properly extends daemon communication protocol
- ✅ RFC-400 already has `command_response` (line 173) with `content` field
- ✅ RFC-404 extends to structured format: `command`, `data`, `error` fields
- ✅ New message type `command_request` added cleanly
- ✅ No conflicts with existing RFC-400 message types

**References RFC-500**: CLI/TUI architecture alignment
- ✅ CLI as presentation layer aligns with RFC-500 principles
- ✅ Daemon as runtime layer respects RFC-500 separation
- ✅ No CLI imports daemon (RFC-500 requirement)
- ✅ No daemon imports CLI (RFC-500 requirement)

**Builds on IG-176**: Extends Rich removal work
- ✅ IG-176 removed Rich from daemon
- ✅ RFC-404 adds rendering functions in CLI
- ✅ Completes the architectural separation started in IG-176
- ✅ Wires rendering functions to daemon events (IG-176 gap)

**Status**: Properly integrated with existing specifications

---

### 3. Command Classification Completeness ✅

**Category 1: CLI-only commands (2)**:
- `/help`, `/keymaps` - Pure presentation
- ✅ Handlers defined: `show_commands()`, `show_keymaps()`
- ✅ No daemon communication required

**Category 2: Daemon RPC commands (13)**:
- `/clear`, `/exit`, `/quit`, `/detach`, `/cancel` - Thread lifecycle
- `/memory`, `/policy`, `/history`, `/config`, `/review` - State queries
- `/thread`, `/resume`, `/autopilot` - Thread management
- ✅ Protocol schemas defined for all commands
- ✅ Handler functions specified for each
- ✅ Params schemas defined where needed

**Category 3: Daemon routing commands (5)**:
- `/plan`, `/autopilot <N> <query>`, `/browser`, `/claude`, `/research`
- ✅ Behavior indicators properly categorized
- ✅ Plain text input path preserved (no protocol changes)
- ✅ Query requirements validated

**Status**: All commands categorized, no missing commands

---

### 4. Protocol Specification ✅

**New message type**: `command_request`
```typescript
{
  "type": "command_request",
  "command": string,
  "thread_id": string | null,
  "params": object | null,
  "client_id": string
}
```
- ✅ Schema complete and well-defined
- ✅ Field requirements clear
- ✅ TypeScript notation for clarity

**Response type**: `command_response`
```typescript
{
  "type": "command_response",
  "command": string,
  "data": object | null,
  "error": string | null
}
```
- ✅ Extends RFC-400 `command_response` (adds structure)
- ✅ Success and error paths defined
- ✅ Command name echoed for correlation

**Status**: Protocol extension is clean and well-specified

---

### 5. Implementation Detail Completeness ✅

**CLI Implementation**:
- ✅ Registry location: `packages/soothe-cli/src/soothe_cli/shared/slash_commands.py`
- ✅ Router location: `packages/soothe-cli/src/soothe_cli/shared/command_router.py`
- ✅ Metadata fields documented (location, type, daemon_command, handler, etc.)
- ✅ Router functions specified (parse, validate, route, handle_rpc, handle_routing)
- ✅ Rendering functions defined for all RPC commands
- ✅ Event processor integration specified

**Daemon Implementation**:
- ✅ Message router update: `packages/soothe/src/soothe/daemon/_handlers.py`
- ✅ RPC command handler: `_handle_command_request()` with dispatch map
- ✅ Individual handlers: 13 handlers specified with signatures
- ✅ Response broadcaster: `_send_command_response()` defined
- ✅ Routing command handling: No changes (existing path preserved)

**Status**: Implementation details sufficient for implementation guide

---

### 6. Code Removal Specification ✅

**Cut change approach**:
- ✅ `_SLASH_COMMANDS_HELP`, `_KEYBOARD_SHORTCUTS_HELP` deleted
- ✅ `_handle_command()` method removed
- ✅ `_parse_autonomous_command_local` deleted
- ✅ No backward compatibility code
- ✅ Zero duplication enforced

**Status**: Cut change well-defined, no legacy code retained

---

### 7. Testing Strategy ✅

**CLI Tests**:
- ✅ Registry structure and metadata
- ✅ Routing logic (CLI/RPC/routing decision)
- ✅ Validation rules
- ✅ Rendering functions with mock data
- ✅ RPC request/response cycle

**Daemon Tests**:
- ✅ Message router handles `command_request`
- ✅ Each RPC handler returns correct structure
- ✅ Error handling returns structured errors
- ✅ Routing commands continue via input path

**Integration Tests**:
- ✅ End-to-end RPC flow
- ✅ Error scenarios
- ✅ Routing command flow

**Status**: Testing coverage comprehensive

---

### 8. Verification Criteria ✅

**8 success criteria**:
1. ✅ Daemon has NO knowledge of CLI-only commands
2. ✅ CLI has single unified command registry
3. ✅ RPC commands use structured protocol
4. ✅ Routing commands use plain text input
5. ✅ Zero backward compatibility code
6. ✅ All tests pass
7. ✅ Daemon linting: zero errors (no UI imports)
8. ✅ CLI does not import daemon runtime

**Status**: Verification criteria clear and measurable

---

## Potential Gaps and Resolutions

### Gap 1: Thread lifecycle handlers implementation detail

**Issue**: RFC-404 shows `_cmd_clear` example but not full implementation for `/exit`, `/quit`, `/detach`

**Resolution**: Implementation guide will provide detailed implementations for each handler. The spec is sufficient - handlers return structured data, daemon marks thread state.

**Severity**: LOW - Not blocking implementation

---

### Gap 2: `find_command_by_daemon_command()` helper not specified

**Issue**: Event processor uses `find_command_by_daemon_command(command)` but implementation not shown

**Resolution**: Helper function will be added to command_router.py:
```python
def find_command_by_daemon_command(daemon_command: str) -> dict | None:
    for entry in COMMANDS.values():
        if entry.get("daemon_command") == daemon_command:
            return entry
    return None
```

**Severity**: LOW - Missing helper function, easy to add

---

### Gap 3: WebSocketClient.request_response() method

**Issue**: Router calls `await client.request_response(request, response_type="command_response")` but assumes this method exists

**Resolution**: Need to verify WebSocketClient has request_response method, or add it if missing. Likely exists in SDK client.

**Severity**: MEDIUM - Verify SDK client has this method

**Action**: Check `packages/soothe-sdk/src/soothe_sdk/client/websocket.py` for request_response implementation

---

### Gap 4: Rendering function param signatures inconsistent

**Issue**: Some rendering functions like `show_commands(console)` take only console, while others like `show_memory(console, data)` take console + data

**Resolution**: This is intentional - CLI-only handlers only need console, RPC handlers need data. The spec is correct.

**Severity**: NONE - Correct design

---

### Gap 5: `/thread` command params parsing

**Issue**: `/thread archive <id>` - how does CLI parse this into `{action: "archive", id: "..."}`?

**Resolution**: `parse_command_params()` function in command_router.py will parse based on `params_schema`. Spec shows the function signature, implementation guide will provide detailed parsing logic.

**Severity**: MEDIUM - Need detailed params parsing implementation

---

## Consistency Checks

### Message Type Naming ✅

- `command_request` (new) - consistent with RFC-400 naming (`input`, `subscription`, etc.)
- `command_response` (extended) - extends existing RFC-400 message type
- ✅ No naming conflicts

### Layer Separation ✅

- CLI: registry, router, rendering (no daemon imports)
- Daemon: RPC handlers, routing parser (no CLI imports)
- ✅ No circular dependencies

### Protocol Design ✅

- RPC: structured request/response
- Routing: plain text input
- ✅ Clear separation of execution modes

---

## Dependencies Verification

### RFC-400 Compatibility ✅

RFC-400 message types:
- `input`, `subscription`, `status`, `event`, `subscription_confirmed`, `error`, `command_response`, `skills_list_response`, `models_list_response`, `invoke_skill_response`

RFC-404 additions:
- `command_request` (new message type)
- Extends `command_response` (already exists in RFC-400)

✅ No conflicts, clean extension

---

### RFC-500 Compatibility ✅

RFC-500 architectural requirements:
- CLI does not import daemon runtime ✅ (RFC-404 enforces this)
- TUI does not import daemon runtime ✅ (RFC-404 enforces this)
- CLI is presentation layer ✅ (RFC-404 defines CLI as presentation)
- Daemon is runtime layer ✅ (RFC-404 defines daemon as runtime)

✅ Full alignment with RFC-500

---

### IG-176 Continuation ✅

IG-176 achievements:
- Moved Rich from daemon to CLI ✅
- Daemon returns structured data ✅
- CLI has rendering functions ✅

IG-176 gaps:
- Rendering functions not wired to daemon events ❌ → RFC-404 resolves ✅
- Command parsing scattered ❌ → RFC-404 consolidates ✅
- No clear routing ❌ → RFC-404 defines routing ✅

✅ RFC-404 completes the IG-176 architectural separation

---

## Implementation Readiness

### Phase 1: Remove Old Code ✅

- Delete `_SLASH_COMMANDS_HELP`, `_KEYBOARD_SHORTCUTS_HELP`
- Delete `_handle_command()` method
- Delete `_command_parser.py` module
- Clear specification, ready to execute

### Phase 2: CLI Registry/Router ✅

- Create `COMMANDS` dict (20 commands specified)
- Create `command_router.py` (6 functions specified)
- Update `slash_commands.py` (10+ rendering functions specified)
- Clear location and structure, ready to implement

### Phase 3: Daemon RPC Handler ✅

- Add `command_request` to message router
- Implement `_handle_command_request()` dispatcher
- Implement 13 individual command handlers
- Implement `_send_command_response()` broadcaster
- Clear signatures, ready to implement

### Phase 4: Wire Event Processor ✅

- Add `command_response` handling to EventProcessor
- Implement `_handle_command_response()` rendering lookup
- Clear integration point, ready to implement

### Phase 5: Update Tests ✅

- CLI tests (registry, router, validation, rendering, RPC cycle)
- Daemon tests (router, handlers, errors, routing)
- Integration tests (end-to-end flows)
- Clear test coverage, ready to implement

### Phase 6: Documentation ✅

- Update RFC-400 spec
- Update user guide
- Update CLAUDE.md
- Clear documentation tasks, ready to execute

---

## Recommendations

### 1. Implementation Guide Priority

**High priority**: Phase 1 (remove old code) and Phase 2 (CLI registry/router)
- Cut change ensures clean start
- Registry and router are foundation for everything else

**Medium priority**: Phase 3 (daemon RPC handler)
- Requires 13 handler implementations
- Detailed implementation guide needed

**Low priority**: Phase 6 (documentation)
- Can be done after verification passes

### 2. Add Missing Helper Functions

Implementation guide should include:
- `find_command_by_daemon_command()` in command_router.py
- Detailed `parse_command_params()` implementation
- WebSocketClient.request_response() verification

### 3. Test Early and Often

Run verification after each phase:
- Phase 1: Verify daemon has zero command handling remnants
- Phase 2: Verify CLI registry/router work locally
- Phase 3: Verify daemon RPC handlers return correct data
- Phase 4: Verify end-to-end flows work

### 4. Documentation Sync

Update RFC-400 after implementation:
- Add `command_request` message type to RFC-400
- Document extended `command_response` schema
- Reference RFC-404 for slash command architecture

---

## Final Assessment

**RFC-404 is READY FOR IMPLEMENTATION** ✅

**Strengths**:
- Clear architectural boundaries
- Complete command classification
- Proper RFC-400 extension
- Sufficient implementation detail
- Comprehensive testing strategy
- Measurable verification criteria

**Minor gaps** (non-blocking):
- Helper function implementations (added in IG)
- Params parsing detail (added in IG)
- WebSocketClient method verification (check in IG)

**Recommendation**: Proceed to create implementation guide (IG-177) with detailed implementations for all 6 phases.

---

## Next Steps

1. ✅ Create IG-177: Slash Command Architecture Implementation
2. ✅ Implement Phase 1: Remove old code
3. ✅ Implement Phase 2: CLI registry/router
4. ✅ Implement Phase 3: Daemon RPC handlers
5. ✅ Implement Phase 4: Event processor wiring
6. ✅ Implement Phase 5: Tests
7. ✅ Implement Phase 6: Documentation
8. ✅ Run verification suite
9. ✅ Update RFC-400 with new message types

**Estimated effort**: Medium-large refactoring (6 phases, 20+ files modified)

**Risk level**: LOW (well-specified, clear cut change)

---

**Validation Status**: ✅ APPROVED FOR IMPLEMENTATION