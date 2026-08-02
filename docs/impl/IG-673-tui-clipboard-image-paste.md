# IG-673: TUI Clipboard Image Paste (`[image N]` Attachments)

## Goal

Support pasting a raw image from the OS clipboard into the Soothe TUI chat
input as an attachment placeholder (e.g. `[image 1]`), matching Cursor Agent
CLI / Hermes-style vision paste UX.

## Motivation

Terminal paste events only carry **text**. An image-only clipboard (screenshot
via Cmd+Ctrl+Shift+4, browser “Copy Image”, etc.) often delivers nothing to
the app. Path-based paste/drag-drop already works via `MediaTracker`, but
users expect Cmd/Ctrl+V to attach clipboard pixels directly.

## Design

| Piece | Choice |
|-------|--------|
| Package | `soothe-cli` only |
| Placeholder | Reuse existing `[image N]` / `MediaTracker` (no wire change) |
| Primary entry | `Ctrl+V` → OS clipboard image read → insert placeholder |
| Fallback entry | `/paste` slash command (same attach path) |
| Empty paste | Bracketed paste with empty/whitespace text also tries clipboard image |
| Path paste | Unchanged (file path → `get_media_from_path`) |
| Submit | Existing `attachments=[{mime_type, data}]` in `textual_adapter` |
| Platform read | Pillow `ImageGrab` when available; else `pngpaste` / `osascript` (macOS), `wl-paste` / `xclip` (Linux), PowerShell (WSL) |
| Failure UX | Toast: no image / too large / missing clipboard tool |
| Size limit | Existing `MAX_MEDIA_BYTES` (20 MB) |

### Non-goals

- Changing placeholder spelling to Cursor’s `[Image #1]` (keep `[image N]`).
- SSH remote clipboard bridging (local OS clipboard only).
- Video clipboard paste (path/drop video remains).

## Files

- `packages/soothe-cli/src/soothe_cli/tui/media_utils.py` — `get_image_from_clipboard`
- `packages/soothe-cli/src/soothe_cli/tui/widgets/chat_input.py` — Ctrl+V, empty paste, attach helper
- `packages/soothe-cli/src/soothe_cli/tui/command_registry.py` — `/paste`
- `packages/soothe-cli/src/soothe_cli/tui/app/_execution.py` — `/paste` handler
- Help / keymap strings (`help_screen.py`, `slash_commands.py`)
- Unit tests under `packages/soothe-cli/tests/unit/ux/tui/`

## Cleanse

- Shared path/clipboard decoding via `image_data_from_bytes` (no duplicate PIL open path).
- No new parallel attachment channel — reuses `MediaTracker` + existing wire `attachments`.
- Removed dead LangChain multimodal builder (`create_multimodal_content` /
  `to_message_content`): the adapter built blocks then discarded them and sent
  text + `attachments` only.
- Removed unused `MediaTracker.get_media` / `get_videos` accessors (images use
  `get_images`; video placeholders remain tracker-local for input UX).

## Validation

- Unit tests for clipboard byte → `ImageData`, attach path (mocked), no-image toast, `/paste` registry
- `./scripts/verify_finally.sh`
