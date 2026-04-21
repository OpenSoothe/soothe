# Fix thread detach issue

## Current issues

1. `Ctrl+D` previously exited the TUI immediately and could race with websocket shutdown, so detach was not always delivered before close.
2. This race could make daemon treat the disconnect as a normal client drop and stop the active run instead of keeping it alive for later reattach.
3. The issue is most visible on long-running turns where users expect `soothe thread continue` to reattach to an in-progress thread.

## Repro / validation checklist

1. Run a long task in TUI, e.g. `soothe -p "analyze this project arch"`.
2. Press `Ctrl+D` to detach.
3. Confirm the thread is still running in daemon (for example via `soothe thread list` status).
4. Run `soothe thread continue` to reattach.
5. Confirm prior history is restored and new streamed events continue in the same thread.

## Notes

1. `Ctrl+D` and explicit detach should share the same detach-before-exit path.
2. If daemon is not used (local/non-daemon mode), `Ctrl+D` should keep normal immediate-exit behavior.
