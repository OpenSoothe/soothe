# IG-088: RFC-0020 Cross-Surface Presentation Policy

**Status**: In Progress
**Created**: 2026-03-28
**Scope**: Implement shared verbosity presentation semantics for both headless CLI and TUI
**RFC References**: RFC-0020, RFC-0003, RFC-0013

---

## Overview

This guide implements the approved RFC-0020 presentation redesign across both headless CLI and TUI surfaces.

Goals:
1. Make `normal` the clean default mode
2. Replace canonical `minimal` with `quiet` (with compatibility alias)
3. Share verbosity semantics across headless and TUI
4. Show plan updates and brief milestones in `normal`
5. Hide internal lifecycle/protocol/debug leakage from `normal`
6. Remove brand messaging and embellishment from user-facing output
7. Add one blank line before every headless output block
8. Preserve equivalent visual separation in TUI via layout/spacing

---

## Core Design

### Shared policy in UX core

Use existing UX core modules as the source of truth:
- `src/soothe/ux/core/display_policy.py`
- `src/soothe/ux/core/event_formatter.py`
- `src/soothe/ux/core/event_processor.py`
- `src/soothe/ux/core/progress_verbosity.py`

### Surface adapters only

Headless and TUI renderers should consume shared presentation decisions rather than reimplement visibility rules independently.

---

## Implementation phases

### Phase 1: Canonical verbosity semantics
- Change canonical verbosity name from `minimal` to `quiet`
- Keep `minimal` as accepted alias at config/CLI/daemon boundaries
- Keep `normal` as default

### Phase 2: Shared response cleaning and extraction
- Add response cleaner for brand/filler stripping
- Add quiet answer extraction with safe fallback
- Route special daemon output through shared cleaner path

### Phase 3: Normal-mode redesign
- Show `Plan:` updates
- Show brief `Done:` milestones
- Hide lifecycle/protocol counters, thread IDs, daemon PIDs, plan reasoning, raw step state, and raw tool spam

### Phase 4: Cross-surface alignment
- Headless: exactly one blank line before each displayed block
- TUI: equivalent visual separation via renderer/widget output
- TUI daemon subscription uses configured verbosity, not hardcoded `normal`

### Phase 5: Tests and verification
- Update unit tests for new semantics and alias compatibility
- Add/adjust integration tests for cross-surface parity
- Run `./scripts/verify_finally.sh`

---

## Files to modify

### Shared core
- `src/soothe/ux/core/display_policy.py`
- `src/soothe/ux/core/event_formatter.py`
- `src/soothe/ux/core/event_processor.py`
- `src/soothe/ux/core/progress_verbosity.py`
- `src/soothe/ux/core/message_processing.py`

### Headless
- `src/soothe/ux/cli/renderer.py`
- `src/soothe/ux/cli/progress.py`
- `src/soothe/ux/cli/execution/daemon.py`
- `src/soothe/ux/cli/execution/standalone.py`

### TUI
- `src/soothe/ux/tui/renderer.py`
- `src/soothe/ux/tui/app.py`
- `src/soothe/ux/tui/widgets.py`
- `src/soothe/ux/core/rendering.py`

### Config / boundaries
- `src/soothe/config/models.py`
- `src/soothe/config/config.yml`
- `src/soothe/ux/cli/main.py`
- `src/soothe/ux/cli/commands/run_cmd.py`
- `src/soothe/daemon/client.py`
- `src/soothe/daemon/_handlers.py`

### Tests
- `tests/unit/test_progress_verbosity.py`
- `tests/unit/test_event_processor.py`
- `tests/unit/test_progress_rendering.py`
- `tests/unit/test_cli_tui_app.py`
- `tests/unit/test_message_processing.py`

---

## Verification checklist

### Manual
- `soothe --no-tui --verbosity normal --prompt "What is the capital of France?"`
- `soothe --no-tui --verbosity normal --prompt "Analyze codebase structure"`
- `soothe --no-tui --verbosity quiet --prompt "Calculate 25 + 17"`
- `soothe --no-tui --verbosity quiet --prompt "List Python files in this project"`
- TUI run using configured verbosity

### Automated
- targeted unit tests for verbosity and cleaning
- targeted integration tests for daemon event flow
- `./scripts/verify_finally.sh`

---

## Risks
- Over-cleaning assistant text
- Drift between shared policy and renderer-specific behavior
- Alias migration bugs for `minimal -> quiet`
- Regressions in plan rendering visibility

Mitigation: implement shared semantics first, keep renderers thin, and test `normal` before polishing `detailed`/`debug`.
