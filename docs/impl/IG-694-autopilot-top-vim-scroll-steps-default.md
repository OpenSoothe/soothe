# IG-694: Autopilot `top` Vim Scroll Keys + Steps Default

**Created**: 2026-08-06  
**Status**: Implemented  
**Related**: [RFC-228 §autopilot_top](../specs/RFC-228-autopilot-job-ipc.md),
[IG-688](IG-688-autopilot-top-interactive-keymaps.md),
[IG-686](IG-686-autopilot-job-artifacts-and-top-polish.md)

---

## Executive Summary

Polish `soothe autopilot top` scrolling to vim **view-mode** motions (page /
half-page / Home / End), and flip the default StepDAG visibility to
`steps=on` while keeping `mode=active`.

Stay on Rich `Live` (no Textual). Letter toggles from IG-688 stay as-is —
paging uses Ctrl chords and physical keys so they do not fight `d` density
or `Space` refresh.

---

## Problem

| Gap | Today (IG-688) |
|-----|----------------|
| Only line scroll + `g`/`G` | Dense forests need page / half-page jumps |
| No PgUp/PgDn/Home/End | CSI sequences unread (`[5~` needs 3+ bytes) |
| Default `steps=off` | Operators usually want plan progress visible |

---

## Design

### Defaults

| Flag | Default | Notes |
|------|---------|-------|
| `include_terminal` | `false` | `mode=active` (unchanged) |
| `show_steps` | **`true`** | was `false` |
| `show_loops` | `true` | unchanged |
| `interval` | `2.0` | unchanged |
| `page_size` | derived | visible body rows minus truncation line |

`d` density still cycles: **full** (new default) → compact → steps-only → full.

### Scroll keymap (vim view-mode subset)

| Key | Action |
|-----|--------|
| `j` / `↓` / `Ctrl-e` | Line down |
| `k` / `↑` / `Ctrl-y` | Line up |
| `Ctrl-d` | Half page down (`max(1, page_size // 2)`) |
| `Ctrl-u` | Half page up |
| `Ctrl-f` / `PgDn` | Page down (`page_size`) |
| `Ctrl-b` / `PgUp` | Page up |
| `g` / `Home` | Top (`scroll = 0`) |
| `G` / `End` | Bottom |

Do **not** steal: `d` (density), `Space` (refresh), `h`/`l` (help/loops),
`+`/`-` (delay). Single `g` remains top (less/`top` style — no `gg` chord).

### Input

Extend `_read_top_key` CSI drain past 2 bytes so `[5~` / `[6~` / `[1~` /
`[4~` work; map common Home/End variants (`[H`/`[F`, `OH`/`OF`). Map
Ctrl letters: `\x04`/`\x15`/`\x06`/`\x02`/`\x05`/`x19` → named keys.

`TopViewState.page_size` is updated in `render_top_snapshot` from the
viewport (`max_body - 1` when truncated).

### Out of scope

Pause/cancel, cursor expand, `gg` pending-state, Textual rewrite, wire changes.

---

## Implementation plan

1. **CLI** — `page_size` on `TopViewState`; `show_steps=True` default;
   `apply_top_key` vim scroll; CSI + Ctrl in `_read_top_key`; help lines.
2. **Docs** — this IG; RFC-228 consumer note; IG-688 default pointer.
3. **Tests** — defaults, scroll keys, optional CSI decode helper.
4. **Verify** — cleanse → `./scripts/verify_finally.sh` → fix.

---

## Acceptance

- [x] Default header: `mode=active (live)`, `steps=on`, `loops=on`
- [x] `Ctrl-d/u/f/b`, `Ctrl-e/y`, PgUp/PgDn, Home/End scroll as above
- [x] `d`/`s`/`l`/`Space` unchanged in meaning
- [x] Help documents vim scroll bindings; no IG/RFC ids in UI strings
- [x] Unit tests green; `./scripts/verify_finally.sh` green

---

| Area | Path |
|------|------|
| IG | `docs/impl/IG-694-autopilot-top-vim-scroll-steps-default.md` |
| CLI | `packages/soothe-cli/src/soothe_cli/cli/commands/autopilot_cmd.py` |
| Tests | `packages/soothe-cli/tests/unit/cli/test_autopilot_top.py` |
| Spec | `docs/specs/RFC-228-autopilot-job-ipc.md` |
