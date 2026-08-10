# IG-738: TUI slash-command Enter one-stage vs two-stage

## Goal

When the slash autocomplete popup is open, Enter should either **execute** the
selected command (one-stage) or **insert** it into the input for further typing
(two-stage), instead of always only completing.

## Behavior

| Key | Behavior |
|-----|----------|
| Tab | Always complete (insert + trailing space) |
| Enter | Follow `SlashCommand.enter_action` / skill default |
| Click | Complete only (avoid accidental quit/clear) |

- **EXECUTE** (`EnterAction.EXECUTE`): complete then `CompletionResult.SUBMIT`
- **COMPLETE** (`EnterAction.COMPLETE`): complete and leave focus in the input

Dynamic `/skill:<name>` rows always use `COMPLETE`.

## Scope

- `packages/soothe-cli/src/soothe_cli/tui/command_registry.py`
- `packages/soothe-cli/src/soothe_cli/tui/widgets/autocomplete.py`
- Unit tests under `packages/soothe-cli/tests/unit/ux/tui/`

## Non-goals

- Changing queue-bypass tiers or command handlers
- Changing Tab / click to execute

## Cleanse (post-impl)

- Removed unused empty `_STATIC_SKILL_ALIASES` filter from skill autocomplete builders
- Updated help shortcut copy for Enter/Tab one-stage vs two-stage behavior
