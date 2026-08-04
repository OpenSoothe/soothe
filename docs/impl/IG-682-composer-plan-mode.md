# IG-682: Composer Plan Mode (Shift+Tab)

**Created**: 2026-08-04
**Status**: Complete
**Related**: RFC-622 (clarification relay), RFC-454 (`/plan` routing), IG-656 (intake-only planner)

## Problem

Operators drafting plans had to type `/plan …` on every turn. Clarification
relay already had a sticky Auto/Manual toggle (Shift+Tab), but there was no
equivalent sticky Plan composer mode.

## Fix

Extend the status-bar composer badge to a three-state cycle:

| Mode | Wire effect |
|------|-------------|
| Auto | `clarification_mode=auto` |
| Manual | `clarification_mode=manual` |
| Plan | `preferred_subagent=planner` + `clarification_mode=auto` |

Binding: **Shift+Tab** cycles Auto → Manual → Plan → Auto (still navigates
filters inside the loop selector). Explicit slash routes (e.g. `/deep_research`)
still win over sticky Plan. `/plan` remains supported.

CLI: `--mode plan` seeds Plan on startup.

## Key files

- `soothe_cli/tui/composer_mode.py` — cycle + wire mapping
- `soothe_cli/tui/widgets/status.py` — badge (teal Plan pill)
- `soothe_cli/tui/app/_messages_mixin.py` — `cycle_composer_mode`
- `soothe_cli/tui/textual_adapter.py` — `sticky_preferred_subagent`
