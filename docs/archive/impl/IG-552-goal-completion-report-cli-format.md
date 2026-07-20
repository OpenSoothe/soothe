# IG-552: Goal Completion Report CLI Format (Phase 1)

**IG**: 552
**Title**: Goal Completion Report CLI Format — Prompt Recipes
**Status**: Implemented
**Created**: 2026-07-06
**RFCs**: RFC-616 (scenario-driven synthesis), RFC-502 (presentation engine, Phase 3 deferred)

## Overview

Phase 1 improves goal-completion synthesis output for CLI/TUI readability via prompt-only formatting rules: GFM tables, bullet lists, and optional Mermaid source blocks (rendered as code until Phase 3).

## Scope

| In scope | Out of scope (later phases) |
|----------|----------------------------|
| `synthesis_report_system.xml` global + per-scenario format hints | Mermaid terminal renderer (`termaid`) |
| `SCENARIO_FORMAT_HINTS` in scenario classifier | Structured JSON report schema |
| Classifier guidance for format-aware `evidence_emphasis` | `PresentationEngine` hook |

## Files

| File | Change |
|------|--------|
| `instructions/synthesis_report_system.xml` | CLI presentation rules |
| `scenario_classifier.py` | `SCENARIO_FORMAT_HINTS`, `format_hint_for_scenario()` |
| `synthesis_projection.py` | Pass `format_hint` into template |
| `classifiers/scenario_classifier_system.xml` | Format-aware evidence_emphasis hint |
| Removed `instructions/synthesis_format.xml` | Legacy template superseded by `synthesis_report_system.xml` |

## Verification

- `packages/soothe/tests/unit/core/loop/engine/test_synthesis_projection.py`
- `./scripts/verify_finally.sh`
