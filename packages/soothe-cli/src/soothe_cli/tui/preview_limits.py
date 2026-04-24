"""Central numeric limits for TUI preview and truncated displays.

Single place to tune how many lines, characters, or items appear in collapsed
or toast-style UI surfaces.
"""

from __future__ import annotations

from typing import Final

# --- Tool call cards (`ToolCallMessage` collapsed output) ---
TOOL_CARD_PREVIEW_LINES: Final[int] = 1
TOOL_CARD_PREVIEW_CHARS: Final[int] = 120
TOOL_CARD_PREVIEW_TODO_ITEMS: Final[int] = 1
TOOL_CARD_PREVIEW_WEB_DICT_KEYS: Final[int] = 1

# --- Skill invocation cards (`SkillMessage` collapsed SKILL.md body) ---
SKILL_CARD_PREVIEW_LINES: Final[int] = 4
SKILL_CARD_PREVIEW_CHARS: Final[int] = 300

# --- Write / edit tool approval widgets (`tool_widgets`) ---
TOOL_APPROVAL_PREVIEW_LINES: Final[int] = 20
TOOL_APPROVAL_VALUE_PREVIEW_CHARS: Final[int] = 200
TOOL_APPROVAL_BODY_MAX_LINES: Final[int] = 30
TOOL_APPROVAL_DIFF_WIDGET_MAX_LINES: Final[int] = 50

# --- Clipboard copy toast ---
CLIPBOARD_TOAST_PREVIEW_CHARS: Final[int] = 40

# --- Security warnings list on approval flows (`approval`) ---
APPROVAL_WARNING_PREVIEW_COUNT: Final[int] = 3
APPROVAL_SHELL_COMMAND_TRUNCATE_CHARS: Final[int] = 120
APPROVAL_WARNING_TEXT_TRUNCATE_CHARS: Final[int] = 220

# --- Unified diff snippets in HITL previews (`file_ops`, diff messages) ---
APPROVAL_DIFF_MAX_LINES: Final[int] = 100

# --- Autopilot dashboard (`autopilot_dashboard`) ---
AUTOPILOT_GOAL_DESCRIPTION_PREVIEW_CHARS: Final[int] = 50
AUTOPILOT_FINDING_LINE_PREVIEW_CHARS: Final[int] = 80
AUTOPILOT_FINDINGS_VISIBLE_COUNT: Final[int] = 20
AUTOPILOT_GRAPH_EDGE_PREVIEW_COUNT: Final[int] = 3
