# IG-172: Daemon model catalog (`models_list`) and per-turn model override

## Status

Implemented.

## Goal

TUI `/model` against a **daemon** must list models from the **daemon host** `SootheConfig`, not the client’s YAML. Choosing a model must affect subsequent turns via websocket `input` without rewriting global defaults.

## Changes

- **Wire RPC**: `models_list` → `models_list_response` (`MessageRouter`, `WebSocketClient.list_models`, `TuiDaemonSession.list_models`).
- **Catalog builder**: `soothe.config.models_catalog.build_models_list_payload` (no `soothe.ux` imports).
- **TUI**: `_show_model_selector` fetches daemon catalog when `_daemon_session` is set; `ModelSelectorScreen` supports `preloaded` + `wire_credential_map`.
- **Override execution**: optional `model` / `model_params` on `input`; `QueryEngine` sets `attach_stream_model_override` for the stream; `PerTurnModelMiddleware` swaps the model via `create_chat_model_for_spec`.
- **API**: `SootheConfig.create_chat_model_for_spec` for explicit `provider:model` construction with merged params.

## Verification

Run `./scripts/verify_finally.sh`.
