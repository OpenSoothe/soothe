# Code Style & Terminology

> Rules governing naming, docstrings, and heuristic-free design.

## Terminology
- NEVER use "layer N" — use concrete names (CoreAgent, StrangeLoop, GoalEngine).
- NEVER expose internal design doc identifiers (e.g. IG-XXX/RFC-XXX) in user-facing text (logs, CLI, errors, config descriptions). Internal only — allowed in comments and internal docs, never in docstrings.
- Only `docs/specs/` (specifications) and `docs/impl/` (design docs) are active references. `docs/archive/` is historical only.

## No Keyword Heuristics
Prefer **structured light-LLM fields** or **declarative config rules** over keyword/regex content-judgment heuristics.
- **Content judgment** (intent, identity, routing, failure classification): Pass 1/2 structured output or a dedicated fast-model call — not keyword lists or regex on user text.
- **Structural controls** (`continue`/`resume`, checkpoint gates, status vocabulary): deterministic rules are fine.
- **Thresholds and banned patterns**: put in config (`agent.loop.rules`, etc.), not magic numbers or inline regex.
- If a keyword/regex heuristic seems required: stop and ask. Propose the LLM or config-rules alternative first.

## Docstrings (MUST)
- Brief and sharp; no verbose prose.
- Module docstring: a few lines stating what the module provides. Do not repeat what function signatures or function docstrings already say.
- Never reference external design docs, reports, or category taxonomies (e.g. "report 5.3", "category I", internal doc identifiers) in docstrings; docstrings must stand alone.
- Class docstrings: describe semantics, coordinate/unit conventions once, args, and a minimal usage example. Do not restate parameter defaults that are obvious from the signature.
- Docstrings must match the implementation; if behavior changes, update the docstring.

## Code Style
- Python ≥3.11, type hints on public functions
- Google-style docstrings (Args, Returns, Raises)
- Ruff for linting/formatting, no bare `except:`
- Single backticks in docstrings: `create_agent()` not ``create_agent()``
