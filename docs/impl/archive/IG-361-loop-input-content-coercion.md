# IG-361: Loop input content coercion

## Status

Complete.

## Problem

`loop_input` RPC placed `msg["content"]` directly on the daemon input queue. Some clients send structured JSON (e.g. `{"text": "..."}`) instead of a bare string, which caused `ThreadLogger.log_user_input` to call `.strip()` on a dict and raise `AttributeError`.

## Approach

- Add `_coerce_loop_input_text()` in `message_router.py` to normalize string or dict-shaped content to a non-empty `str | None`.
- Reject invalid payloads with the existing `INVALID_REQUEST` path when coercion returns `None`.

## Verification

Run `./scripts/verify_finally.sh` after code changes.
