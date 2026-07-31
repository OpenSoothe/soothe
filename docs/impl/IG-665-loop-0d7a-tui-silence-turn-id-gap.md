# IG-665: Loop 0d7a TUI silence (turn_id + gap analysis)

**Created**: 2026-07-31
**Status**: Complete
**Incident**: loop `019fb5cd-18ae-7b90-8a1b-0b3c44b60d7a` (`0d7a`)
**Related**: IG-616 (turn_id boundary), IG-593 (gap wire coerce), IG-655 (live cards)

## Problem

After the bump-step assistant summary, the TUI looked frozen for ~4 minutes.

1. **Card frames omit `turn_id`** — `LoopCardManager` broadcasts via raw `_broadcast`, bypassing `QueryEngine._loop_scoped_client_message`. Client drops `type=event` with absent `turn_id` when a turn is bound (hundreds of ignores per turn).
2. **Gap analysis schema thrash** — `PlanGapAnalysis` LLM output often omits `component` and overflows `max_length` fields; structured invoke walks function_calling → None → json_schema → json_mode with repairs (~230s wall clock).
3. **Spinner label mismatch** — backend emits `Analyzing coverage` / `Assessing progress` / `Assessing continuation`; CLI spinner map must use those canonical labels (not outdated synonyms).

## Fix (phase 1 — done)

| Area | Change |
|------|--------|
| Daemon `_broadcast` | Stamp `turn_id`+`seq` from active `_broadcast_turn_generation` when absent (skip pre-admit / no active turn) |
| `plan_gap_wire` | Synthesize missing `component`, truncate overlong strings, clamp list sizes, normalize distance enum |
| Planner gap invoke | Prefer `json_schema` then `json_mode` |
| CLI spinner map | Map canonical backend plan-phase labels |

## Fix (phase 2)

| Area | Change |
|------|--------|
| Gap node | Wall-clock budget; catch timeout/`ValueError`/any failure → `plan_gap=None` → assess |
| Gap invoke | Methods `json_schema`/`json_mode` only; tight per-call timeout (no execute-scale retries) |
| Prompt cards | Record user prompt **after** admit sets `_broadcast_turn_generation` (not pre-admit) |
| Handler error idle | Explicit `turn_generation` from active/admitted gen (or omit when pre-admit) |

## Non-goals

- Changing client turn_id filter semantics (absent must not match).
- Stamping pre-admit early `running` with prior generation (IG-616).
