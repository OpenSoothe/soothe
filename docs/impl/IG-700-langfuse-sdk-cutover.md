# IG-700: Langfuse SDK Cutover (No Shim Paths)

## Goal

Move shared Langfuse observability utilities out of `soothe-nano` and into `soothe-sdk`, then update `soothe`, `soothe-nano`, and `soothe-daemon` to import SDK paths directly (hard cut; no compatibility shims).

## Scope

- Add SDK package modules:
  - `soothe_sdk.observability.langfuse._types`
  - `soothe_sdk.observability.langfuse._client`
  - `soothe_sdk.observability.langfuse._handlers`
  - `soothe_sdk.observability.langfuse._merge`
  - `soothe_sdk.observability.langfuse._trace_io`
  - `soothe_sdk.observability.langfuse._names`
  - `soothe_sdk.observability.langfuse.callback_handler`
  - `soothe_sdk.observability.langfuse.system_hint`
  - `soothe_sdk.observability.langfuse.tracer`
  - `soothe_sdk.observability.langfuse.__init__`
- Switch runtime imports in:
  - `packages/soothe/`
  - `packages/soothe-nano/`
  - `packages/soothe-daemon/`
- Remove old `soothe_nano` Langfuse module files.
- Update tests and monkeypatch paths to SDK modules.
- Rename nano root run-name constant to `nanoagent-graph`.

## Design Notes

- SDK modules are typed against a `SootheConfigLike` protocol instead of importing package-specific config classes.
- Env placeholder resolution (`${VAR}`) is implemented in SDK `_client.py` to avoid dependency on `soothe_nano.config.env`.
- Host-specific StrangeLoop behavior remains in `soothe` (`GoalLoopTrace`, host run-name helpers), but uses SDK Langfuse primitives.

## Verification

- Run targeted Langfuse unit tests for `soothe-nano` and `soothe`.
- Run final repository verification:
  - `./scripts/verify_finally.sh`

