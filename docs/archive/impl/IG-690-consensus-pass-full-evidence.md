# IG-690: Consensus Judge Must Receive Full Response / Evidence

**Created**: 2026-08-05  
**Status**: Implemented  
**Related**: [IG-680](IG-680-autopilot-dag-health-evidence-deps.md),
[IG-685](IG-685-consensus-full-output-evidence.md),
[IG-688](IG-688-autopilot-top-interactive-keymaps.md) (top defaults: steps off, 2s refresh),
[RFC-204](../specs/RFC-204-autopilot-mode.md),
[RFC-222](../specs/RFC-222-autopilot-goal-engine-architecture.md)

---

## Problem

Autopilot consensus suspends goals that already produced grounded completion
evidence because the **judge prompt truncates** response and evidence to 500
characters via `preview_first`.

Incident pattern (job `20999e64`, Wave 1 maker `[tests]` / goal `712dc11e`):

1. Worker runs tools, commits on isolation branch, synthesizes evidence.
2. `_apply_consensus_and_finalize` builds grounded text (summary + files +
   probe).
3. `evaluate_goal_completion` → `_build_consensus_prompt` wraps both
   `response` and `evidence` with `preview_first(..., 500)`.
4. Consensus LLM reasons: evidence is truncated/abbreviated → **`suspend`**.
5. DAG health monitor reactivates the suspended blocker → thrash loop.

IG-685 fixed empty-evidence grounding (`full_output` / plan steps). It did
**not** stop the consensus prompt from clipping what it then asks the model to
verify.

Encoded regression: `test_prompt_truncates_long_response` asserts
`len(prompt) < 1000` for a 1000-char response — that encodes the bug.

---

## Scope

### In

1. Pass **full** `response` and `evidence` into the consensus judge prompt
   (no `preview_first` on judge inputs).
2. Rename prompt labels (`Agent Response Preview` → `Agent Response`) so the
   model is not primed to treat input as incomplete.
3. Keep `preview_first` for **log** lines only.
4. Update unit tests; remove truncation-as-success assertion.
5. Optional soft guidance: if evidence still looks incomplete, prefer
   `send_back` over `suspend` for truncation-only complaints (prompt text
   only — no keyword heuristics on user content).

### Out (follow-ups, not this IG)

- Raising `synthesize_completion_evidence` 2048 cap.
- Expanding workspace probes beyond Python/pytest (cargo / git branch).
- Structural accept override for non-pytest deliverables.
- Monitor suspend↔reset thrash caps.

---

## Design

### Prompt builder (`consensus.py`)

Pass full strings:

```python
f"\nAgent Response:\n{response}"
parts.append(f"\nEvidence Summary:\n{evidence}")
```

No soft cap in this IG (prefer none until soak shows context blowups).
`preview_first` remains on consensus **log** lines only.

Decision guidance addition (prompt text):

- `suspend` = fundamentally blocked / needs external input.
- Do **not** choose `suspend` solely because the narrative is short when
  evidence lists commits, files, or workspace probe hits.
- Prefer `send_back` when more verification detail is needed.

### Call path (unchanged wiring)

`service._apply_consensus_and_finalize` already passes `grounded` as both
`response_text` and evidence into `evaluate_goal_completion`. This IG only
stops the prompt builder from discarding that text.

### Tests

| Change | File |
|--------|------|
| Replace `test_prompt_truncates_long_response` with preserve-long-text | `tests/unit/core/autopilot/test_consensus.py` |
| Assert long response + evidence appear verbatim; no “Preview” label | same |
| Keep accept/send_back/suspend structured-verdict tests | same |

---

## Implementation checklist

- [x] Edit `_build_consensus_prompt` in
  `packages/soothe/src/soothe/autopilot/consensus.py`
- [x] Update / replace truncation unit test in
  `packages/soothe/tests/unit/core/autopilot/test_consensus.py`
- [x] Confirm log path still uses `preview_first(reasoning, …)` only
- [x] Cleanse: no leftover “Preview” labels or 500-char judge caps
- [x] `./scripts/verify_finally.sh` green

---

## Acceptance

- [x] Consensus prompt includes a multi-kilobyte response/evidence string
      without clipping to 500 chars
- [x] Prompt does not use `Agent Response Preview` wording
- [x] Unit tests assert preservation; old truncation assertion removed
- [ ] Suspend-for-abbreviation false positive path is no longer forced by
      the prompt builder (manual: resume a maker goal with rich evidence)
- [x] Verify script green

---

## Files

| Path | Role |
|------|------|
| `packages/soothe/src/soothe/autopilot/consensus.py` | Prompt builder fix |
| `packages/soothe/tests/unit/core/autopilot/test_consensus.py` | Regression tests |
| `packages/soothe/src/soothe/autopilot/service.py` | Call site (unchanged) |

---

## Notes

- User-facing logs/CLI must not mention this IG id (AGENTS.md §7).
- Internal docstrings/comments may reference IG-690.
