# IG-171: TUI `/model` thread-scoped override

## Status

Complete (local agent path).

## Goal

`/model` should pick a model for the **current thread** that can differ from `config.yml`, without mutating global TUI `settings` or recent-model files. Overrides clear when the user starts a new thread (`/clear`) or resumes another thread (`/threads`).

## Scope

- **In scope:** Local in-process agent + `ConfigurableModelMiddleware` via `CLIContext` in `execute_task_textual`.
- **Out of scope:** Daemon-backed TUI (server must choose model); surfaced as an explicit error until protocol support exists.

## Changes

- `SootheApp._switch_model`: validate with `create_model`, set `_model_override` / `_model_params_override`, no `apply_to_settings()` or `save_recent_model`.
- `SootheApp._clear_thread_model_override`: reset overrides and status bar to `settings` defaults; call from `/clear` and `_resume_thread` after a successful thread switch.
