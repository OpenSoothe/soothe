# IG-128: Layer 2 Reason — thread context, display hygiene, and TUI completion styling

**Status:** Implemented  
**Spec traceability:** RFC-0008 (agentic loop), RFC-0020 (event / stream presentation)  
**Platonic phase:** Implementation (IMPL) — code + tests + verification

---

## 1. Overview

This guide covers work to make **follow-up goals** in the same thread (e.g. translate prior assistant output) work reliably in the **Layer 2 LoopAgent**, and follow-on fixes for **truncation**, **duplicate “Done” walls**, **final report UX**, and **TUI progress prefix colors** for completion lines.

---

## 2. Problem statement

### 2.1 Reason without prior conversation

- Tier-1 routing could see recent checkpointer messages, but **Reason** (`build_loop_reason_prompt`) did not.
- `PlanContext.recent_messages` existed but was never wired: `LoopState` had no real field (only a dead `previous_messages` `hasattr` check), and `build_loop_reason_prompt` did not render `recent_messages`.
- Result: goals like「翻译成中文」could be classified as `medium` yet **Reason** declared `done` with **zero Act steps** because the model had no prior text in-prompt.

### 2.2 Truncation and duplicate UI

- Prior-conversation excerpts used a **uniform 8k** cap per message → long English briefs were cut for translation context.
- Agentic **final stdout** used an **8k** display ceiling → long Chinese output looked “截断”.
- TUI showed **subagent** assistant chunks as **80-character** lines → unreadable long translations.
- `soothe.agentic.loop.completed` registry template used **`Done: {evidence_summary}`**; model or merged evidence could repeat **full** step output → **duplicate** streamed answer plus a **500-char truncated** “Done: Step step_0: ✓ …” line.

### 2.3 TUI prefix color for “Done”

- Progress lines with **empty namespace** used **`protocol` (`dim white`)**; with **subagent namespace**, **`magenta`** — easy to read as error/red. **Completion** lines were not semantically green.

---

## 3. Implementation plan (phased)

| Phase | Goal | Outcome |
|-------|------|---------|
| A | Inject prior thread text into Reason | Checkpointer tail → `reason_conversation_excerpts` → `PlanContext.recent_messages` → `<SOOTHE_PRIOR_CONVERSATION>` + follow-up policy in `build_loop_reason_prompt` |
| B | Boundaries for long text | Last **Assistant** excerpt **100k** chars; older turns **8k**; agentic final report **200k** stdout cap + spool; TUI full **subagent** stream buffer |
| C | Final report UX when spooled | Truncated preview ends with **`...`**; line **`Full report: <path>`** or glob hint if write fails |
| D | Loop completion one-liner | `completion_summary` on `AgenticLoopCompletedEvent`; template **`Done: {completion_summary}`**; cap runaway **evidence_summary** in Reason phase; clip **step.started** description for events |
| E | TUI success color | `_progress_event_dot_color`: **green** (`plan_step_done`) for loop completed / reason done / step completed success |

---

## 4. File structure and changes

| Area | Path | Change |
|------|------|--------|
| Loop state | `src/soothe/cognition/loop_agent/schemas.py` | `reason_conversation_excerpts: list[str]` on `LoopState` |
| Loop agent | `src/soothe/cognition/loop_agent/loop_agent.py` | `run_with_progress(..., reason_conversation_excerpts=...)`; `_build_plan_context` uses `reason_conversation_excerpts` for `recent_messages` |
| Runner phases | `src/soothe/core/runner/_runner_phases.py` | `_format_thread_messages_for_reason` (last AIMessage **100_000** cap, others **8_000**) |
| Runner agentic | `src/soothe/core/runner/_runner_agentic.py` | Single `_load_recent_messages` tail for routing + reason; `_clip_agentic_step_description`; `completion_summary` + `AgenticLoopCompletedEvent`; constants **200_000** final cap / preview; `_agentic_final_stdout_text` ellipsis + `Full report:` |
| Planning prompt | `src/soothe/backends/planning/simple.py` | `<SOOTHE_PRIOR_CONVERSATION>` + `<SOOTHE_FOLLOW_UP_POLICY>` when `context.recent_messages` |
| Reason phase | `src/soothe/cognition/loop_agent/reason.py` | If model `evidence_summary` **> 600** chars → prefer compact step-derived evidence or **400** + ellipsis |
| Events | `src/soothe/core/event_catalog.py` | `AgenticLoopCompletedEvent.completion_summary`; registry template **`Done: {completion_summary}`** |
| TUI formatter | `src/soothe/ux/shared/event_formatter.py` | `build_event_summary`: default `completion_summary` for legacy payloads |
| TUI renderer | `src/soothe/ux/tui/renderer.py` | Subagent streams **full** text via `_stream_assistant_panel_text`; `_progress_event_dot_color` for green completion |
| Tests | `tests/unit/test_reason_prompt_workspace.py` | Prior conversation in Reason prompt |
| Tests | `tests/unit/test_runner_agentic_final_stdout.py` | Spool / ellipsis / `Full report:` |
| Tests | `tests/unit/test_event_formatter.py` | `completion_summary` / defaults |
| Tests | `tests/unit/test_tui_progress_dot_colors.py` | Green prefix for done-style events |

---

## 5. Behaviour notes

- **Routing vs Reason:** Tier-1 still uses the last **6** messages; Reason excerpts use up to **16** messages from checkpointer (same load, sliced).
- **`completion_summary`:** Prefer `ReasonResult.user_summary`, else `"{n} step(s) complete"`, max **240** chars — avoids duplicating streamed translation in the **Done:** line.
- **LangSmith / token metrics:** Not part of this IG; see separate observability work if product wants prompt-token gauges.

---

## 6. Testing strategy

- Unit: Reason prompt includes prior conversation block; `build_event_summary` for `soothe.agentic.loop.completed`; agentic final stdout spool and `...` suffix; TUI color helper.
- Regression: existing CLI renderer / pipeline tests for `loop.completed` payloads (formatter defaults preserve old dicts without `completion_summary`).

---

## 7. Verification

```bash
./scripts/verify_finally.sh
```

---

## 8. Platonic coding alignment

| Artifact | Location |
|----------|----------|
| Implementation guide (this doc) | `docs/impl/IG-128-loop-reason-prior-conversation.md` |
| Specs | RFC-0008 agentic loop; RFC-0020 presentation tiers (event summaries, TUI dots) |
| Next maintenance | If context-window metrics are required, add a dedicated IG + hooks (callbacks / `usage_metadata`), not ad-hoc logs in LoopAgent only |

---

## 9. Changelog (session summary)

1. IG-128 initial: prior conversation → Reason prompt + `LoopState` / `PlanContext` wiring.  
2. Truncation: 100k last assistant; 200k final report display; TUI full subagent stream.  
3. Final report: `...` + `Full report: <path>` / glob on failure.  
4. Display hygiene: `completion_summary`, evidence cap, step description clip, formatter `setdefault`.  
5. TUI: green `●` for loop completed / reason done / successful step completed.
