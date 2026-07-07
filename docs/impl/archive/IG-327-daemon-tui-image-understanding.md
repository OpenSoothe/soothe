# IG-327: Daemon + TUI image understanding

**Status**: Completed  
**Scope**: WebSocket (and internal queue) `input` messages with optional image attachments; vision preflight using `SootheConfig.create_chat_model("image")`; TUI daemon path sends attachments; tests.

## Wire schema (`type: input`)

- **`text`** (string, required): User text; may be empty when attachments are present.
- **`attachments`** (optional): Array of objects:
  - `mime_type` (string): Must be one of `image/png`, `image/jpeg`, `image/webp`, `image/gif`, `image/bmp` (aliases like `image/jpg` normalized to `image/jpeg`).
  - `data` (string): Standard base64 (no `data:` prefix); decoded size per image ≤ 20 MiB; at most **8** images per message.

Validation:

- Structural checks in [`protocol_v2.validate_message`](packages/soothe/src/soothe/daemon/protocol_v2.py).
- Size / MIME / base64 in [`daemon/image_understanding.py`](packages/soothe/src/soothe/daemon/image_understanding.py); invalid payloads → `INVALID_MESSAGE` via `_send_client_message` from [`MessageRouter`](packages/soothe/src/soothe/daemon/message_router.py).

## Thread logging

- [`ThreadLogger.log_user_input`](packages/soothe/src/soothe/logging/thread_logger.py) receives **enriched text only** (vision summary + delimiters + user text), never raw base64 payloads.

## HTTP REST

- Thread resume (`POST .../resume`) remains **text-only** for this IG; parity deferred.

## Loop RPC

- `loop_input` unchanged (no attachments in this IG).

## References

- Plan: Daemon + TUI image understanding (vision preflight).
- Toolkit precedent: [`packages/soothe/src/soothe/toolkits/image.py`](packages/soothe/src/soothe/toolkits/image.py) (`create_chat_model("image")`).
