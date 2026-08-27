# Structured `ask_user` Widget — Design Draft

**Date:** 2026-08-27
**Status:** Draft
**Topic:** Redesign the generic (execute) `ask_user` render path into a structured multi-question option-picker widget.

---

## Problem

The current `ask_user` tool (`packages/soothe/src/soothe/coreagent/tools/ask_user.py`) accepts `questions: list[str]` — plain text only. When the loop interrupts for a human answer, the CLI (`ClarificationInputMessage`) renders a single free-text `Input` per question in generic mode. The model has no way to offer the user structured choices (options with short/long descriptions, a recommended pick, a custom fallback). Every answer requires the user to type free text, even for simple routing or approval decisions outside the HITL plan/tool gates.

This is a UX gap: for decision-gate questions that don't rise to the level of plan review or tool approval (e.g. "which auth method?", "Redis or Postgres for the token store?", "exponential or fixed backoff?"), the user must type a full answer instead of picking from the model's suggested options.

## Goal

A structured `ask_user` widget where:

- The LLM emits **structured question specs**: title (≤3 words, tab label), description (≤100 words), exactly 3 options (each with a short label and a long description), and a recommended index.
- The widget renders **multiple questions as tabs** with left/right navigation.
- Within each question, the user **highlights options with ↑/↓** (the highlighted option's long description expands inline), and **Enter selects**.
- A **4th "custom" row** lets the user type a free-text answer instead of picking a suggested option.
- A **persistent footer** with Submit/Abandon is reachable from any question. Submit opens an inline recap (all Q→answer-title pairs), then Enter confirms or Abandon cancels.
- Plan-review and tool-approval HITL modes stay untouched — this redesign affects the generic (execute) render path only.

## Non-Goals

- No changes to the `plan_mode_review` or `tool_approval` render modes or their HITL wire decode contract.
- No wire migration for HITL origins — `ClarificationInputMessage` keeps its 3-button option selector for those two origins.
- No structured-option support for HITL modes in this pass (a future RFC may unify them).

## Architecture

### Two widget classes, two wire contracts

| Widget | Wire contract | Purpose |
|--------|---------------|---------|
| `ClarificationInputMessage` | HITL decisions — host decodes `Approve`/`Refine`/`Reject` → `decision` types | Plan review, tool approval |
| `StructuredAskUserWidget` (new) | Free-text or option-short answers — `list[str]` resume payload | Generic (execute) ask_user |

`ClarificationInputMessage` loses its `_compose_generic` path; it now only renders option-selector modes. `StructuredAskUserWidget` is the new home for all non-HITL ask_user rendering.

### Backward compatibility

In-flight interrupts from before the schema upgrade carry plain-string questions. The CLI routing layer detects this by payload shape and mounts `StructuredAskUserWidget` in a **degraded mode**: one free-text `Input` per question + a simple Submit button (no tabs, no options). This is a narrow shim (~15 lines), not a maintained second mode — once the model is upgraded, this path is dead.

## Components

### 1. Host schema (`ask_user.py`)

```python
class OptionSpec(BaseModel):
    short: str   # ≤12 words — the answer label shown in the recap and sent on resume
    long: str    # 1–3 sentences — shown in the hover-preview box

class QuestionSpec(BaseModel):
    title: str           # ≤3 words — tab label
    description: str     # ≤100 words — shown under the tab
    options: list[OptionSpec]  # exactly 3
    recommended: int     # 0–2 (index into options); -1 = no recommendation

class _AskUserArgs(BaseModel):
    questions: list[QuestionSpec]
```

**Validators:**
- `OptionSpec.short`: ≤12 words (whitespace-split count)
- `OptionSpec.long`: 1–3 sentences, non-empty
- `QuestionSpec.title`: ≤3 words
- `QuestionSpec.description`: ≤100 words
- `QuestionSpec.options`: exactly 3 entries (reject if ≠3)
- `QuestionSpec.recommended`: in `[-1, 2]` (reject if out of range)
- `_AskUserArgs._normalize`: strip empty/invalid question entries; reject if none survive. Drop the `question`/`query` singular aliases — structured questions can't be expressed as a single string.

### 2. Wire protocol

**Host → CLI** (interrupt payload):
```json
{
  "type": "ask_user",
  "questions": [
    {
      "title": "Auth method",
      "description": "How should the API authenticate requests?",
      "options": [
        {"short": "OAuth 2.0", "long": "OAuth 2.0 with PKCE. Best for browser flows."},
        {"short": "API key", "long": "Static API key in a header. Simplest to implement."},
        {"short": "Session", "long": "Server-side session with cookies. Best for SSR apps."}
      ],
      "recommended": 0
    }
  ]
}
```

**CLI → host** (resume payload, unchanged format):
```json
{"answers": ["OAuth 2.0", "Redis", "custom text…"]}
```
Each entry is the selected option's `short` text, or the custom free-text. `_format_answers` extracts `title` from `QuestionSpec` for the `Q:` line (falls back to `str(q)` for plain-string backward compat).

### 3. CLI widget (`structured_ask_user.py`, new file)

**Class:** `StructuredAskUserWidget(Vertical)` in `packages/soothe-cli/src/soothe_cli/tui/widgets/messages/structured_ask_user.py`.

**Layout:**

```
┌─ Tab bar ──────────────────────────────────────────────┐
│ ✓ Q1   ✓ Q2   ▸Q3                                      │
├─────────────────────────────────────────────────────────┤
│  Title: "Retry policy"                                  │
│  Description: "How should we handle transient           │
│  failures in the message consumer?"                     │
│                                                         │
│  ▸ 1. Exponential backoff (recommended)                 │
│    ┌─────────────────────────────────────────┐          │
│    │ Double the delay each retry, up to 60s. │          │
│    │ Best for network hiccups and rate limits.│          │
│    └─────────────────────────────────────────┘          │
│    2. Fixed delay                                       │
│    3. Circuit breaker                                   │
│    4. Custom: [_____________________________]           │
├─────────────────────────────────────────────────────────┤
│  2/3 answered            [Submit]  [Abandon]            │
│  ←/→ questions  ↑/↓ options  Enter select  Tab footer   │
└─────────────────────────────────────────────────────────┘
```

**Tab bar:** One tab per question. Tabs show `✓` when the question has a selected answer. The active tab shows `▸` prefix. Titles are the `QuestionSpec.title` (≤3 words).

**Option list:** 3 model-provided options + a 4th "Custom" row with an inline `Input`. The recommended option shows "(recommended)" suffix. ↑/↓ cycles through all 4 rows. The highlighted option's `long` description expands in a bordered preview box below it. Unhighlighted options show only their `short` label.

**Custom row:** When highlighted, the inline `Input` is enabled and focusable. Typing text + Enter finalizes the custom answer for that question. Selecting custom with empty text blocks submit (shows hint).

**Footer:** Persistent bar at the bottom. Shows `N/M answered` count + `[Submit]` (disabled until all answered) + `[Abandon]`. Reachable via `Tab` from any question. When Submit is pressed, an inline recap block renders above the footer:

```
  Review:
    Q1: Auth method  → OAuth 2.0
    Q2: Token store  → Redis
    Q3: Retry policy → Exponential backoff

  [Submit]  [Abandon]
```

Enter on Submit finalizes; Enter on Abandon cancels (posts `Submitted` with empty answers).

**Answered state (per question):** once a question has a selection, the selected option row is bold/success-colored. The user can navigate back to that question and change the selection — nothing is final until Submit.

**Submitted state (final):** after Submit, the widget collapses to a summary view: each question title + the selected answer, similar to `ClarificationInputMessage`'s `is-submitted` answered view. Tabs, options, and footer are hidden.

**Single question:** when there is only one question, the tab bar is hidden (no siblings to switch between), ←/→ are no-ops, and the footer Submit enables as soon as the one question is answered. Everything else (↑/↓ options, Enter select, custom row, Submit recap) works identically.

**`Submitted` message:** `StructuredAskUserWidget` defines its own `Submitted(Message)` — it does not reuse `ClarificationInputMessage.Submitted`. The two widgets serve disjoint wire contracts; their submit messages are independent. (The CLI handler already routes by widget type, so there's no cross-dispatch.)

### Keybindings

| Key | Action | Scope |
|-----|--------|-------|
| ← | Previous question tab | Question area |
| → | Next question tab | Question area |
| ↑ | Highlight previous option | Question area |
| ↓ | Highlight next option | Question area |
| Enter | Select highlighted option (or finalize custom text) | Question area |
| Tab | Move focus to footer (Submit → Abandon → back to question) | Anywhere |
| Esc | Abandon (from footer or question area) | Anywhere |

Note: ←/→ in this widget switch questions, **not** cycle options. This differs from `ClarificationInputMessage` where ←/→ cycle the 3 HITL actions. The two widgets have disjoint keybinding semantics because they serve disjoint wire contracts — no conflict since only one is mounted at a time.

### State

```python
_current_question_idx: int          # active tab
_selected: dict[int, int]           # question_idx → option_idx (0–2) or 3 (custom)
_custom_texts: dict[int, str]       # question_idx → custom text (only if _selected[q]==3)
_highlighted_option: int           # 0–3 within current question
_submit_review_open: bool          # whether the recap block is showing
_submitted: bool                    # final submit done
```

### 4. `ClarificationInputMessage` changes

- **Delete:** `_compose_generic`, `_finalize`, `_on_input_submitted` (generic path), and the generic-mode CSS blocks (the `Input` styling that's not shared with the refine input).
- **Keep:** `Submitted` message class, `_schedule_focus`, `_assemble_card_header`/`_card_body_gutter` helpers, the option-selector compose/finalize path.
- `compose()` simplifies to: `if self._is_option_selector: yield from self._compose_option_selector()`. The generic branch is gone — routing won't mount this widget for generic questions anymore.

### 5. CLI routing (clarification handler)

```python
def _build_clarification_widget(payload):
    questions = payload.get("questions", [])
    if questions and isinstance(questions[0], dict) and "options" in questions[0]:
        return StructuredAskUserWidget(
            questions=questions,
            step_id=payload["step_id"],
            widget_id=payload.get("widget_id"),
        )
    # Degraded fallback: plain-string questions from old in-flight interrupts.
    return StructuredAskUserWidget(
        questions=questions,
        step_id=payload["step_id"],
        widget_id=payload.get("widget_id"),
        degraded=True,
    )
```

In degraded mode, the widget renders one free-text `Input` per question + a simple Submit button — no tabs, no options, no hover-preview.

## Data Flow

```
LLM calls ask_user(questions=[QuestionSpec(...)])
    │
    ▼
Host validates schema → interrupts: {type:ask_user, questions:[q.model_dump()]}
    │
    ▼
Daemon sends clarification.requested → CLI
    │
    ▼
CLI routing: questions[0] is dict with "options"?
    │ yes                              │ no (degraded)
    ▼                                 ▼
mount StructuredAskUserWidget      mount StructuredAskUserWidget(degraded=True)
    │
    ▼
User: ←/→ tabs, ↑/↓ highlight, Enter select, Tab→Submit, Enter confirm
    │
    ▼
Widget posts Submitted(answers=[short_text_or_custom, ...])
    │
    ▼
CLI sends answers to daemon → host resumes graph
    │
    ▼
_format_answers → "User answered:\nQ: {title}\nA: {answer}" → model continues
```

## Error Handling

- **Model emits ≠3 options** → host `QuestionSpec` validator rejects with `ValueError` → tool error returned to model for retry.
- **`recommended` out of range** → validator rejects → model retries.
- **Title >3 words or description >100 words** → validator rejects → model retries.
- **Custom selected but empty text** → widget blocks submit, shows "Enter a custom answer or pick an option" hint inline.
- **Submit before all questions answered** → Submit button disabled (grey, not focusable).
- **Abandon** → posts `Submitted` with empty answers → `_format_answers` returns dismissal text → model gets "Clarification dismissed without an answer. Decide how to proceed."

## Testing

- **Host unit:** `_AskUserArgs` validation — 3 options, recommended range, title/desc word limits, empty rejection, `model_validator` behavior.
- **Host unit:** `_format_answers` with `QuestionSpec` objects — title extraction, answer pairing.
- **CLI unit:** `StructuredAskUserWidget` compose, ←/→/↑/↓ navigation, Enter selection, custom Input flow, Submit recap, Abandon, submitted collapsed view.
- **CLI unit:** degraded path (plain-string questions) renders free-text inputs.
- **Integration:** extend `test_ask_user_tool.py` and `test_loop_agent_clarification_round_trip.py` for structured round-trip (interrupt → mount → answer → resume).

## Migration

- Wire-breaking change: the `questions` field changes from `list[str]` to `list[QuestionSpec]`. Old in-flight interrupts are handled by the degraded fallback path. No dual-write period — the host tool is upgraded in one commit; the CLI widget lands in the same release.
- No data migration needed — interrupts are ephemeral, not persisted as structured records (only the transcript stores the rendered Q&A text).
