# IG-657: TUI Mermaid Rendering for Goal-Completion Reports

## Goal

Render fenced ` ```mermaid ` blocks in assistant markdown (especially
goal-completion synthesis reports) as terminal Unicode/ASCII diagrams instead
of raw source code fences.

## Motivation

IG-652 / synthesis prompts already ask Phase 2 for mermaid flowcharts and
sequence diagrams. Rich TUI markdown treated those fences as Pygments code
blocks, so users saw source instead of a chart.

## Design

| Piece | Choice |
|-------|--------|
| Package | `soothe-cli` only (display). Host keeps emitting mermaid source. |
| Library | `termaid` (pure Python; flowchart + sequence) |
| Hook | Override Rich `Markdown` fence/`code_block` element for `mermaid` / `mmd` |
| Timing | Expand only on final markdown pass (already post-stream) |
| Failure | Empty/invalid/unsupported → fall back to normal code fence |
| Width | Progressive gap/padding compaction to fit card `max_width` |
| Scope | flowchart / `graph` primary; sequenceDiagram when termaid succeeds |

## Files

- `packages/soothe-cli/pyproject.toml` — `termaid` dependency
- `packages/soothe-cli/src/soothe_cli/tui/mermaid_render.py` — render + auto-fit
- `packages/soothe-cli/src/soothe_cli/tui/markdown_theme.py` — mermaid-aware `CodeBlock`
- `packages/soothe/src/soothe/sloop/engine/scenario_classifier.py` — note update
- Unit tests under `packages/soothe-cli/tests/unit/ux/tui/`

## Cleanse (related legacy / dead)

- Deleted obsolete `packages/soothe-cli/docs/TUI_RENDERING_BOTTLENECK_ANALYSIS.md`
  (MarkdownStream-era bottleneck notes superseded by two-phase plain→themed
  markdown + IG-657 mermaid expand).
- Replaced stale `MarkdownStream` comment in `textual_adapter` with current
  `stop_stream` / themed-markdown wording.
- Dropped unused `render_mermaid_rich` wrapper; call sites use `render_mermaid_art`.

## Validation

- `./scripts/verify_finally.sh`
