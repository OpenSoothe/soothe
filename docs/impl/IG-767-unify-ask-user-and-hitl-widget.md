# IG-767: Unify ask_user and HITL Widget

**Created**: 2026-08-28
**Status**: Implemented
**Related**: RFC-622 §9c (structured ask_user schema + widget), IG-766 (structured
ask_user widget), IG-765 (unified ask_user/tool_approval relay)

## Problem

Plan review and tool approval used a separate widget (`ClarificationInputMessage`)
from the generic `ask_user` widget (`StructuredAskUserWidget`). The two widgets
rendered the same conceptual UI — a set of options the user picks from — but
differed only in that HITL options were system-prefilled (Approve/Refine/Reject)
rather than LLM-emitted. This duplicated ~600 lines of CSS, compose logic,
focus management, and serialization code.

## Goal

Collapse `ClarificationInputMessage` into `StructuredAskUserWidget`. HITL origins
(plan_mode_review, tool_approval) now route through the same widget with
`allow_custom=False`, a comment field on the Refine/Edit option, and optional
plan body rendering. One widget, one CSS namespace, one serialization path.

## Design

### 1. StructuredAskUserWidget extensions

New constructor params:
- `body_markdown` / `body_path` — plan body rendering (plan review only)
- `allow_custom: bool = True` — suppresses the "Other" free-text row for HITL
- `comment_option_index: int | None` — option index that shows a comment input

New HITL helpers:
- `_is_hitl` / `_is_plan_review` / `_is_tool_approval` properties
- `_tool_approval_title()` — origin-aware title builder
- `_path_footer_text()` — plan path display
- `_toggle_body_expanded()` — expand/collapse plan body in answered view
- `on_click` / `on_descendant_focus` — body toggle + comment focus guard

Origin-aware rendering:
- Title: "Review this plan" (plan) / "Approve tool: ..." (tool) / "Awaiting your answer" (generic)
- Answered view: action label + comments + expand toggle (plan) / "Approved" (tool)
- Comment input: shown when the Refine/Edit option is selected; Enter submits

### 2. Host-side detector changes

`ClarificationDetector._format_action_request` now returns a `QuestionSpec`
dict with 3 options (Approve, Edit, Reject) instead of a plain string. The
`header` field carries the tool name + informative arg.

`_PLAN_MODE_REVIEW_QUESTIONS` changed from `tuple[str, ...]` to
`tuple[dict, ...]` — a single `QuestionSpec` dict with 3 options
(Approve, Refine, Reject).

### 3. CLI routing unification

`_mount_manual_clarification_input` in `textual_adapter.py` now routes all
origins through `StructuredAskUserWidget`. HITL origins get `allow_custom=False`
and `comment_option_index` set to the Refine/Edit option's index.

The event processing code no longer flattens HITL questions to strings —
structured dicts are preserved for all origins.

### 4. Serialization (binding.py)

`message_from_widget` handles `StructuredAskUserWidget` with HITL origins:
- Submitted HITL → `MessageType.PLAN_REVIEW` with action, comments, plan body
- Awaiting HITL → `MessageType.APP` with "Plan review: awaiting..." content
- Non-HITL → `MessageType.APP` (unchanged)

`message_to_widget` reconstructs a `StructuredAskUserWidget` (not
`ClarificationInputMessage`) for `PLAN_REVIEW` messages.

### 5. Event handler unification

`_execution.py` now has a single `on_structured_ask_user_widget_submitted`
handler for all origins. The old `on_clarification_input_message_submitted`
handler is deleted.

### 6. Wire contract — unchanged

The host-side `build_clarification_resume_payload` already branches on
`origin_node == ORIGIN_TOOL_APPROVAL`. The widget sends answer strings
(option labels), and the existing decoders handle them:
- `parse_plan_review_answers(["Approve", ""])` → `("approve", "")`
- `_answer_to_decision("Approve")` → `"approve"`

The `InteractiveClarificationPolicy._extract_answers` now preserves both
`[action, comment]` slots for HITL origins (previously truncated to
`[:expected]`).

## Files

- `packages/soothe-cli/src/soothe_cli/tui/widgets/messages/structured_ask_user.py` — HITL extensions
- `packages/soothe-cli/src/soothe_cli/tui/widgets/messages/clarification.py` — **deleted**
- `packages/soothe-cli/src/soothe_cli/tui/widgets/messages/__init__.py` — removed ClarificationInputMessage export
- `packages/soothe-cli/src/soothe_cli/tui/textual_adapter.py` — unified routing
- `packages/soothe-cli/src/soothe_cli/tui/app/_execution.py` — unified handler
- `packages/soothe-cli/src/soothe_cli/tui/app/_messages_mixin.py` — updated reference
- `packages/soothe-cli/src/soothe_cli/commands/binding.py` — updated serialization
- `packages/soothe/src/soothe/sloop/clarification/detector.py` — QuestionSpec for tool approval
- `packages/soothe/src/soothe/sloop/plans/plan_mode_review.py` — QuestionSpec for plan review
- `packages/soothe/src/soothe/sloop/clarification/interactive.py` — preserve comment slot

## Verification

`./scripts/verify_finally.sh` — zero lint, all tests green.
