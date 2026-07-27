# IG-652: Goal Synthesis LLM Outline + Markdown-First Reports

## Goal

Let the synthesis model own the report outline (soft suggestions, not fixed
builtin headings) and enforce a scan-first Markdown contract: bullets, tables,
code fences, and mermaid over long prose.

## Motivation

RFC-616 already intended LLM-designed sections, but:

1. Heuristic fast-paths copy `BUILTIN_SCENARIOS` section lists.
2. Phase 2 prompts treat those lists as **required** headings.
3. CLI formatting rules are soft preferences, so reports drift into paragraphs.

## Design (Option A)

| Piece | Change |
|-------|--------|
| Heuristics | Keep structural latency skips; **do not** fill `sections` from builtins (empty → Phase 2 invents). |
| Classifier LLM | Builtins are style hints; always design goal-specific `sections` (3–7) as suggestions. |
| Phase 2 prompt | Soft “Suggested outline”; hard structure/Markdown rules; prose budget. |
| `content_draft` | Short paragraphs allowed for narrative body; all other styles bullets/tables first. |
| Format hints | Layout examples only (tables/mermaid), not outline authority. |

## Files

- `scenario_classifier.py` / classifier XML prompts — empty heuristic `sections`;
  style catalog = `_SCENARIO_DESCRIPTIONS` (removed `BUILTIN_SCENARIOS` section lists)
- `synthesis_report_system.xml` / `user_message.py` TASK — soft outline + Markdown-first
- Unit tests: scenario classifier + synthesis projection

## Cleanse (related dead code)

- Deleted unused `prompts/fragments/system/response_guides/`
  (`architecture_analysis`, `research_synthesis`, `loop_continuation`) and their
  fragment exports — superseded by scenario-driven + IG-652 Markdown contract.
- Fixed stale module docs pointing at deleted `policies/goal_completion_policy.py`
  / `analysis/*.py` paths.

## Validation

- `./scripts/verify_finally.sh`
