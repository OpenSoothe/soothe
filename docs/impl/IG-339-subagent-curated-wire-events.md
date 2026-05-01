# IG-339: Curated `soothe.subagent.*` wire events (metadata-only)

**Status**: Implemented  
**Scope**: `soothe-sdk` allowlist + payload clipping, built-in subagent emitters, CLI `StreamDisplayPipeline` + IG-334 `task_scope`, TUI Task card notes.

## Summary

- **Hard cut**: `soothe.capability.*` removed from producers and clients; no dual emit.
- **Contract**: Allowlisted type strings and bounded fields in `soothe_sdk.core.subagent_wire`; emit via `soothe.utils.subagent_emit.emit_subagent_wire_event`.
- **UX**: All allowlisted `soothe.subagent.*` wire events classify to NORMAL (sparse metadata-only payloads). CLI progress lines include `[Task(type):tool_call_id]` when IG-334 scope is present. TUI appends one short line per allowlisted event to the parent **Task** `ToolCallMessage` when the task card is known.

## Documentation alignment

- [RFC-403](../specs/RFC-403-unified-event-naming.md) §8.4 — canonical naming and obsolete `soothe.capability.*` note
- [RFC-501](../specs/RFC-501-display-verbosity.md) §6.1 — `classify_event_to_tier` NORMAL override for `soothe.subagent.*`
- [event-catalog](../specs/event-catalog.md) — built-in allowlist summary (Subagent Events)
- [RFC-613](../specs/RFC-613-explore-agent-llm-orchestrated-search.md) §5.5 — Explore agent wire events

## Verification

```bash
./scripts/verify_finally.sh
```
