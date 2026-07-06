"""Central numeric limits for TUI preview and truncated displays.

Single place to tune how many lines, characters, or items appear in collapsed
or toast-style UI surfaces.
"""

from __future__ import annotations

from typing import Final

# --- Step cognition cards (`CognitionStepMessage`) ---
# When False, step cards show the latest N tool activity lines in the branch tree
# (task + main-agent scopes) plus per-kind counts on the running status line.
# When True, the full nested tool list also renders in `#step-cognition-tools`.
STEP_CARD_SHOW_TOOL_ROW_DETAILS: Final[bool] = False

# Latest per-tool invocation lines on step and SubAgent cards (shared activity tree).
STEP_CARD_TOOL_ACTIVITY_PREVIEW_COUNT: Final[int] = 3

# Optional manual full tool-list folding threshold (not auto-collapse).
STEP_TASK_CARD_COLLAPSE_LINE_THRESHOLD: Final[int] = 3

# --- Skill invocation cards (`SkillMessage` collapsed SKILL.md body) ---
SKILL_CARD_PREVIEW_LINES: Final[int] = 4
SKILL_CARD_PREVIEW_CHARS: Final[int] = 300

# --- Write / edit / delete file change preview widgets (`file_change_preview`) ---
TOOL_APPROVAL_PREVIEW_LINES: Final[int] = 8
TOOL_APPROVAL_VALUE_PREVIEW_CHARS: Final[int] = 200
TOOL_APPROVAL_BODY_MAX_LINES: Final[int] = 8
TOOL_APPROVAL_DIFF_WIDGET_MAX_LINES: Final[int] = 8

# --- Clipboard copy toast ---
CLIPBOARD_TOAST_PREVIEW_CHARS: Final[int] = 40

# --- Chat input: large paste abbreviation (display only; submit uses full text) ---
CHAT_INPUT_PASTE_ABBREVIATE_LINE_COUNT: Final[int] = 4
CHAT_INPUT_PASTE_ABBREVIATE_CHAR_COUNT: Final[int] = 240
CHAT_INPUT_PASTE_PREVIEW_HEAD_LINES: Final[int] = 2
CHAT_INPUT_PASTE_PREVIEW_TAIL_LINES: Final[int] = 1
CHAT_INPUT_PASTE_PREVIEW_LINE_MAX_CHARS: Final[int] = 76

# --- Security warnings list on approval flows (`approval`) ---
APPROVAL_WARNING_PREVIEW_COUNT: Final[int] = 3
APPROVAL_SHELL_COMMAND_TRUNCATE_CHARS: Final[int] = 120
APPROVAL_WARNING_TEXT_TRUNCATE_CHARS: Final[int] = 220

# --- Unified diff snippets in chat (`file_ops`, DiffMessage) ---
APPROVAL_DIFF_MAX_LINES: Final[int] = 15

# --- Autopilot dashboard (`autopilot_dashboard`) ---
AUTOPILOT_GOAL_DESCRIPTION_PREVIEW_CHARS: Final[int] = 50
AUTOPILOT_FINDING_LINE_PREVIEW_CHARS: Final[int] = 80
AUTOPILOT_FINDINGS_VISIBLE_COUNT: Final[int] = 20
AUTOPILOT_GRAPH_EDGE_PREVIEW_COUNT: Final[int] = 3
