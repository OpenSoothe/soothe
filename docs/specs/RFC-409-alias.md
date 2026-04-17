# RFC-409 (Alias) - Deprecated

**Status**: Alias - Moved to RFC-203
**Redirect**: This RFC has been moved to RFC-203 (AgentLoop State & Memory Architecture)
**Reason**: CheckpointEnvelope is Layer 2 implementation, not DurabilityProtocol (RFC merge proposal 2026-04-17)

## Original Content Moved To

**RFC-203: AgentLoop State & Memory Architecture**

**Moved Components**:
- RFC-409 (CheckpointEnvelope) → RFC-203 §Loop Unified State Checkpoint
- RFC-409 content integrated into AgentLoop Layer 2 implementation

## See Current Version

**RFC-203**: `docs/drafts/2026-04-17-rfc-203-agentloop-state-management-merged.md`

## Migration Notes

- CheckpointEnvelope is AgentLoop execution state (Layer 2), NOT thread metadata (DurabilityProtocol)
- Separation clarified: DurabilityProtocol = thread lifecycle metadata, CheckpointEnvelope = execution state
- All progressive checkpoint content preserved in RFC-203
- Backward compatibility maintained through this alias

---

*Alias created 2026-04-17 during RFC consolidation Phase 2.*