# Skillify Agent Implementation Guide

**Guide**: IG-011
**Title**: Skillify Agent Implementation
**Created**: 2026-03-13
**Related RFCs**: RFC-0001, RFC-0002, RFC-0003, RFC-0004

## Overview

This guide describes how to implement the Skillify agent as a Soothe-compatible subagent that curates and serves reusable skills. It translates RFC-0004 into concrete implementation phases, file organization, validation criteria, and testing expectations.

## Prerequisites

- [x] RFC-0001 available
- [x] RFC-0002 available
- [x] RFC-0003 available
- [x] RFC-0004 drafted
- [x] Existing vector store and persistence abstractions implemented (IG-006)

## Deliverables

| Area | Deliverable |
|------|-------------|
| Subagent runtime | `skillify` subagent registration and wiring |
| Warehouse | Durable filesystem structure under Skillify workspace |
| Registry | Skill metadata state machine + provenance records |
| Indexing | Embedding + retrieval via `VectorStoreProtocol` |
| Integration | Policy checks and protocol event emission |

## Suggested File Structure

```text
src/soothe/subagents/skillify.py              # Skillify SubAgent/CompiledSubAgent
src/soothe/skills/skillify/                   # Internal helper skills if needed
src/soothe/skillify/
  sources.py                                  # source adapters
  normalizer.py                               # deepagents skill normalization
  registry.py                                 # lifecycle metadata store
  indexer.py                                  # vector indexing and search
  service.py                                  # retrieval service
```

> Keep module boundaries swappable; concrete classes should depend on protocol interfaces where possible.

## Implementation Plan

### Phase 1: Configuration and wiring

- Add `skillify` section in `SootheConfig`
- Register Skillify in subagent factory and routing config
- Define workspace path defaults and environment overrides

### Phase 2: Warehouse + registry

- Implement durable warehouse path creation
- Create registry records with lifecycle statuses:
  - `candidate`
  - `validated`
  - `published`
  - `deprecated`
- Store provenance: source URI, fetch timestamp, hash, validator version

### Phase 3: Normalization and validation

- Normalize raw source content to deepagents-compatible skill package
- Validate required files and metadata presence
- Add quality scoring and rejection reasons

### Phase 4: Indexing and retrieval

- Create embeddings using configured embedding model
- Persist vectors through `VectorStoreProtocol`
- Implement objective-to-skill retrieval API with metadata filters and top-k

### Phase 5: Curation loop + events

- Implement periodic curation run orchestration
- Add policy checks before acquisition and publication actions
- Emit `soothe.skillify.*` events for observability

## Testing Strategy

### Unit tests

- Registry lifecycle transitions and invalid transition handling
- Normalizer output contract (`SKILL.md` present + metadata integrity)
- Index insert/search behavior with mocked vector store
- Retrieval ranking with policy-filtered candidates

### Integration tests

- End-to-end ingest from a stub source into warehouse + index
- Retrieval flow returns bounded, ranked skill sets
- Resume behavior after interrupted curation run

## Verification Checklist

- [ ] Skillify is routable as a Soothe subagent
- [ ] Warehouse artifacts are durable across restarts
- [ ] Every registry record includes provenance metadata
- [ ] Retrieval uses vector index + metadata filters
- [ ] Policy denials are enforced and observable
- [ ] Custom events for curation/retrieval are emitted

## Rollout Notes

- Start with read-only retrieval mode against pre-seeded skills.
- Enable scheduled curation after policy profiles are validated.
- Add quality threshold tightening gradually to avoid starving discovery.

## Related Documents

- [RFC-0004](../specs/RFC-0004.md) - Skillify Agent Architecture Design
- [IG-006](./006-vectorstore-router-persistence.md) - VectorStore, Router, Persistence
