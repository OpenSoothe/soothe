# IG-766: Structured ask_user Widget

**Created**: 2026-08-27
**Status**: Draft
**Related**: RFC-622 §9c (structured ask_user schema + widget), RFC-622 §4.3 (ClarificationInputMessage changes), IG-765 (unified ask_user/tool_approval relay — the routing target shares this spine)

## Problem

The `ask_user` tool (`packages/soothe/src/soothe/coreagent/tools/ask_user.py`) accepts `questions: list[str]` — plain text only. The CLI (`ClarificationInputMessage` in `clarification.py`) renders a single free-text `Input` per question in generic (execute) mode. The model cannot offer the user structured choices (options with short/long descriptions, a recommended pick, a custom fallback). For decision-gate questions that don't rise to HITL plan review or tool approval, the user must type a full answer instead of picking from suggested options.

## Goal

Implement RFC-622 §9c: change the `ask_user` tool args to `list[QuestionSpec]`, build a `StructuredAskUserWidget` for the CLI with tab navigation + hover-preview option selection + persistent Submit/Abandon footer, and remove the generic free-text render path from `ClarificationInputMessage`. HITL plan-review and tool-approval modes stay untouched.

## Design

### 1. Host schema (`ask_user.py`)

Add `OptionSpec` and `QuestionSpec` Pydantic models. Change `_AskUserArgs.questions` from `list[str]` to `list[QuestionSpec]`. Drop the `question`/`query` singular aliases.

```python
class OptionSpec(BaseModel):
    short: str
    long: str

class QuestionSpec(BaseModel):
    title: str
    description: str
    options: list[OptionSpec]
    recommended: int = -1

    @model_validator(mode="after")
    def _validate(self) -> QuestionSpec:
        if len(self.options) != 3:
            raise ValueError("exactly 3 options required")
        if self.recommended not in (-1, 0, 1, 2):
            raise ValueError("recommended must be -1, 0, 1, or 2")
        if len(self.title.split()) > 3:
            raise ValueError("title must be ≤3 words")
        if len(self.description.split()) > 100:
            raise ValueError("description must be ≤100 words")
        for opt in self.options:
            if len(opt.short.split()) > 12:
                raise ValueError("option short must be ≤12 words")
        return self

class _AskUserArgs(BaseModel):
    questions: list[QuestionSpec] = Field(default_factory=list)

    @model_validator(mode="after")
    def _normalize(self) -> _AskUserArgs:
        self.questions = [q for q in self.questions if q.title.strip()]
        if not self.questions:
            raise ValueError("ask_user requires at least one non-empty question")
        return self
```

Update `_format_answers` to extract `title` from `QuestionSpec` (fall back to `str(q)` for plain-string backward compat):

```python
def _format_answers(questions: list[str], payload: object) -> str:
    raw = payload.get("answers", payload) if isinstance(payload, dict) else payload
    answers = (
        [raw] if isinstance(raw, str) else [str(a) for a in raw] if isinstance(raw, list) else []
    )
    if not answers:
        return "Clarification dismissed without an answer. Decide how to proceed."
    pairs = []
    for i, q in enumerate(questions):
        title = q.title if isinstance(q, QuestionSpec) else str(q)
        pairs.append(f"Q: {title}\nA: {answers[i] if i < len(answers) else '(no answer)'}")
    return "User answered:\n" + "\n".join(pairs)
```

The `interrupt()` call in `_run_ask_user` must serialize `QuestionSpec` objects: `interrupt({"type": "ask_user", "questions": [q.model_dump() for q in cleaned]})`.

### 2. CLI widget (`structured_ask_user.py`, new file)

New `StructuredAskUserWidget(Vertical)` at `packages/soothe-cli/src/soothe_cli/tui/widgets/messages/structured_ask_user.py`.

**Constructor:**

```python
class StructuredAskUserWidget(Vertical):
    class Submitted(Message):
        def __init__(self, *, step_id, questions, answers, widget_id, origin_node=""):
            super().__init__()
            self.step_id = step_id
            self.questions = questions
            self.answers = answers
            self.widget_id = widget_id
            self.origin_node = origin_node

    def __init__(self, *, step_id, questions, widget_id=None,
                 origin_node=None, degraded=False, **kwargs):
        super().__init__(**kwargs)
        self._step_id = step_id
        self._questions = questions        # list[dict] (structured) or list[str] (degraded)
        self._degraded = degraded
        self._origin_node = (origin_node or "").strip()
        self._widget_id = widget_id or self.id or ""
        self._current_q = 0
        self._selected: dict[int, int] = {}     # q_idx → option_idx (0–2) or 3 (custom)
        self._custom_texts: dict[int, str] = {}
        self._highlighted = 0
        self._submit_review_open = False
        self._submitted = False
        self._inputs: list[Input] = []          # degraded-mode inputs
```

**Keybindings (BINDINGS):**

```python
BINDINGS = [
    Binding("left", "prev_question", "Prev question", show=False),
    Binding("right", "next_question", "Next question", show=False),
    Binding("up", "prev_option", "Prev option", show=False),
    Binding("down", "next_option", "Next option", show=False),
    Binding("enter", "confirm", "Confirm", show=False),
    Binding("tab", "focus_footer", "Footer", show=False),
    Binding("escape", "abandon", "Abandon", show=False),
]
```

**Compose:**
- `_degraded=True`: title + one `Input` per plain-string question + Submit button. No tabs, no options.
- `_degraded=False`: tab bar (`Horizontal` of `Static` labels showing `✓`/`▸` + title) + question body (title, description, 4 option rows with hover-preview box for highlighted) + footer (`N/M answered`, Submit button, Abandon button).

**Navigation logic:**
- `prev_question` / `next_question`: cycle `_current_q` within `[0, len(questions)-1]`; skip when only one question. Re-render the question body.
- `prev_option` / `next_option`: cycle `_highlighted` within `[0, 3]` (3 options + custom row). Update the preview box to show the highlighted option's `long` desc.
- `confirm` (Enter): if `_highlighted < 3`, set `_selected[_current_q] = _highlighted`; if `_highlighted == 3`, focus the custom `Input` (Enter in the Input finalizes with the typed text → `_selected[_current_q] = 3`, `_custom_texts[_current_q] = text`). After selecting, auto-advance to the next unanswered question if any remain.
- `focus_footer` (Tab): move focus to Submit or Abandon button (cycle between them). Tab again returns to the question area.
- `abandon` (Esc): post `Submitted(answers=[])`.

**Submit flow:**
- Submit button is disabled (`.set_class(False, "-active")` or `disabled=True`) until `len(_selected) == len(questions)`.
- Pressing Submit sets `_submit_review_open = True` and renders the recap block inline above the footer (each question title → selected answer's `short` text or custom text). The recap shows two buttons: `[Submit]` (confirm) and `[Abandon]`.
- Enter on the recap's Submit: collect `answers = [selected option's short text or custom text for each question]`, set `_submitted = True`, add `is-submitted` class, post `Submitted(answers=answers)`.
- Enter on the recap's Abandon: post `Submitted(answers=[])`.

**Answered state:**
- Selected option row: bold + success color.
- Tab shows `✓`.
- User can navigate back and re-select; the selection updates until Submit is finalized.

**Submitted state:**
- Collapse to summary: each question title + selected answer (parity with `ClarificationInputMessage.is-submitted`).
- Hide tabs, options, footer via CSS (`is-submitted` class toggles `display: none`).

**CSS (DEFAULT_CSS):**
- Tab bar: `Horizontal`, labels are `Static` widgets; active tab gets `▸` prefix + accent color; answered tab gets `✓` + success color.
- Option rows: `Static` for the short label; highlighted row gets `▸` prefix; preview box is a bordered `Static` that updates on highlight change.
- Custom row: `Input` with placeholder "Type a custom answer…"; enabled only when highlighted.
- Footer: `Horizontal` with `Static` (count) + `Button` (Submit) + `Button` (Abandon). Submit `disabled` until all answered.

### 3. ClarificationInputMessage changes (`clarification.py`)

Delete the generic-mode code path:

- `_compose_generic` method — delete.
- `_finalize` method — delete (only the generic path used it; the option-selector path has `_finalize_plan_review` and `_finalize_plan_review_with_comments`).
- `_on_input_submitted` — delete the generic branch (the `if self._is_option_selector: ... return` guard and everything after it for generic). Keep the option-selector branch for the refine input.
- Generic-mode CSS blocks: the `ClarificationInputMessage Input` rules that aren't shared with the refine input. Keep `Input.plan-review-refine-input` and the `is-submitted Input` rule.
- `compose()`: simplify to `if self._is_option_selector: yield from self._compose_option_selector()`. Remove the `else: yield from self._compose_generic()` branch. If `compose()` yields nothing (non-option-selector origin), the widget shouldn't be mounted for that origin anymore — the routing layer handles it.

Keep: `Submitted` message class, `_schedule_focus`, `_assemble_card_header`/`_card_body_gutter` helpers, the option-selector compose/finalize path.

### 4. CLI routing (`textual_adapter.py`)

Two change sites:

**Site A — `_mount_manual_clarification_input` (line ~2924):**

Add a `degraded` parameter and routing logic. The function currently takes `questions: list[str]` and flattens each entry via `str(q)`. Change it to preserve structured dicts:

```python
async def _mount_manual_clarification_input(
    adapter: TextualUIAdapter,
    *,
    questions: list,  # list[str] | list[dict] (QuestionSpec)
    origin_node: str = "",
    plan_path: str = "",
    plan_markdown: str = "",
) -> str:
    ...
    # Route by payload shape.
    is_structured = (
        questions
        and isinstance(questions[0], dict)
        and "options" in questions[0]
    )
    if is_structured or origin_node in ("", "execute"):
        from soothe_cli.tui.widgets.messages.structured_ask_user import (
            StructuredAskUserWidget,
        )
        input_widget = StructuredAskUserWidget(
            step_id=target_step_id,
            questions=questions,
            origin_node=origin_node,
            widget_id=widget_id,
            id=widget_id,
            degraded=not is_structured,
        )
    else:
        # HITL origins stay on ClarificationInputMessage.
        input_widget = ClarificationInputMessage(
            step_id=target_step_id,
            questions=[str(q) for q in questions],
            origin_node=origin_node,
            plan_path=plan_path,
            plan_markdown=plan_markdown,
            widget_id=widget_id,
            id=widget_id,
        )
    ...
```

**Site B — event handler (line ~4203):**

Stop flattening structured questions to `str(q)`:

```python
raw_questions = data.get("questions") or []
# Preserve structured dicts; only flatten for HITL origins.
if origin_node in ("plan_mode_review", "tool_approval"):
    questions_list = [str(q) for q in raw_questions if str(q).strip()]
else:
    questions_list = [q for q in raw_questions if (str(q) if isinstance(q, str) else q.get("title", "")).strip()]
```

**Site C — `binding.py` (line ~153):**

The second `ClarificationInputMessage(` instantiation site (in the command/binding layer) needs the same routing logic. If it's only used for HITL origins, leave it; otherwise apply the same `is_structured` check. Check the call site context during implementation — if it's a replay/resume path that always carries an `origin_node`, route accordingly.

### 5. Transcript / MessageData serialization

The `Submitted` message from `StructuredAskUserWidget` carries `questions` (list of dicts or strings) and `answers` (list of strings). The transcript serializer (`MessageData`) must handle dict-valued questions. If the current serializer assumes `questions: list[str]`, add a `model_dump`/JSON serialization path for dict questions. The answered-state restore (`on_mount` with `_submitted=True`) must reconstruct the widget from persisted data — ensure the `questions` field round-trips through JSON.

Check: `soothe_cli/tui/widgets/messages/_helpers.py` or the transcript adapter for `MessageData` serialization. The `questions` field may need `list[dict | str]` typing.

## Files

| File | Change |
|------|--------|
| `packages/soothe/src/soothe/coreagent/tools/ask_user.py` | Add `OptionSpec`, `QuestionSpec`; change `_AskUserArgs.questions` to `list[QuestionSpec]`; update `_format_answers` for title extraction; serialize in `_run_ask_user` interrupt. |
| `packages/soothe-cli/src/soothe_cli/tui/widgets/messages/structured_ask_user.py` | **New file.** `StructuredAskUserWidget` class, `Submitted` message, compose, navigation, submit/abandon, CSS. |
| `packages/soothe-cli/src/soothe_cli/tui/widgets/messages/clarification.py` | Delete `_compose_generic`, `_finalize`, generic branch of `_on_input_submitted`, generic CSS. Simplify `compose()`. |
| `packages/soothe-cli/src/soothe_cli/tui/textual_adapter.py` | `_mount_manual_clarification_input` (line ~2924): route by payload shape; event handler (line ~4203): stop flattening structured questions. |
| `packages/soothe-cli/src/soothe_cli/commands/binding.py` | Second `ClarificationInputMessage` instantiation (line ~153): apply same routing if needed. |
| Transcript `MessageData` serialization | Handle `questions: list[dict | str]` for round-trip. |

## Testing

### Host unit (`packages/soothe/tests/unit/coreagent/test_ask_user_tool.py`)

- `OptionSpec` / `QuestionSpec` validation: exactly 3 options, `recommended` range `[-1, 2]`, title ≤3 words, description ≤100 words, option short ≤12 words.
- `_AskUserArgs` normalization: empty-question rejection, whitespace-only rejection.
- `_format_answers` with `QuestionSpec` objects: title extraction, answer pairing, dismissal text on empty answers.
- `_run_ask_user` interrupt payload shape: `{"type": "ask_user", "questions": [q.model_dump(), ...]}`.

### CLI unit (new: `test_structured_ask_user.py`)

Create `packages/soothe-cli/tests/.../tui/widgets/messages/test_structured_ask_user.py`:

- Compose: tab bar renders N tabs; question body renders title, description, 4 option rows.
- Navigation: ←/→ switches `_current_q`; ↑/↓ cycles `_highlighted`; Enter selects; Tab moves to footer.
- Custom row: highlighting row 3 enables the Input; Enter in Input with text finalizes custom answer; empty text blocks submit.
- Submit flow: disabled until all answered; pressing Submit shows recap; Enter on recap Submit finalizes → `Submitted` posted with correct answers.
- Abandon: Esc posts `Submitted` with empty answers.
- Submitted state: `is-submitted` class added; tabs/options/footer hidden; summary shows title + answer.
- Single question: tab bar hidden; ←/→ no-ops; Submit enables on first answer.
- Degraded mode: plain-string questions render free-text Inputs + Submit; no tabs/options.

### Integration (extend existing)

- `test_loop_agent_clarification_round_trip.py`: structured round-trip (interrupt with `QuestionSpec` → mount `StructuredAskUserWidget` → answer → resume → model receives formatted Q&A).
- `test_ask_user_and_interrupt_on_e2e.py`: ensure HITL origins still mount `ClarificationInputMessage` unchanged.

## Verification

`./scripts/verify_finally.sh` — zero lint, all tests green. The existing HITL end-to-end tests (`test_ask_user_and_interrupt_on_e2e.py`) must pass unchanged.

## Implementation Order

1. Host schema (`ask_user.py`) — `OptionSpec`, `QuestionSpec`, validators, `_format_answers`, interrupt serialization.
2. Host unit tests — schema validation, format answers.
3. CLI widget (`structured_ask_user.py`) — full widget with CSS.
4. CLI widget unit tests — navigation, submit, abandon, degraded.
5. `ClarificationInputMessage` cleanup — delete generic path, simplify `compose()`.
6. CLI routing (`textual_adapter.py`, `binding.py`) — payload-shape routing.
7. Transcript serialization — `questions: list[dict | str]` round-trip.
8. Integration tests — structured round-trip, HITL regression.

## Risks

- **Wire-breaking change**: in-flight interrupts from before the schema upgrade carry plain-string questions. The degraded fallback handles this, but only if the CLI correctly detects the payload shape. Verify with a mixed-payload integration test.
- **Textual keybinding conflicts**: ←/→ in `StructuredAskUserWidget` switch questions, while `ClarificationInputMessage` uses ←/→ to cycle HITL actions. Only one widget is mounted at a time, so no runtime conflict — but verify the app-level keybinding dispatcher doesn't intercept ←/→ before the widget.
- **Transcript round-trip**: if `MessageData.questions` is typed `list[str]`, structured dicts may break deserialization. Check the serializer early in implementation.
- **`binding.py` second instantiation**: if this path is used for resume/replay, it may need the same routing. Verify its call-site origin during step 6.
