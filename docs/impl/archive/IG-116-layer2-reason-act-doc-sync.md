# IG-116: Layer 2 Reason → Act Documentation Sync

**Status**: In Progress
**Related**: RFC-201, RFC-200, RFC-000, IG-115 (Reason → Act migration)

## Goal

Update all outdated references to the old "PLAN → ACT → JUDGE" architecture to reflect the current **Reason → Act** model across specs, docs, source comments, and configuration.

## Scope

### P0: Source code (dead config + stale comments)
- `src/soothe/config/models.py` - dead `use_judge_engine` field
- `src/soothe/config/config.yml` - dead config key + stale comments
- `src/soothe/core/runner/__init__.py` - stale docstring
- `src/soothe/core/README.md` - stale comment

### P1: RFC specs (canonical docs must reflect current architecture)
- `docs/specs/RFC-201-agentic-goal-execution.md` - primary spec (14+ refs)
- `docs/specs/RFC-200-autonomous-goal-management.md` - Layer 3 spec (10+ refs)
- `docs/specs/RFC-000-system-conceptual-design.md` - conceptual design (2 refs)
- `docs/specs/RFC-204-autopilot-mode.md` - autopilot spec (2 refs)
- `docs/specs/RFC-301-protocol-registry.md` - dead param ref
- `docs/specs/rfc-index.md` - index entry
- `docs/specs/rfc-namings.md` - terminology update

### P2: User-facing docs
- `README.md` (3 refs)
- `docs/wiki/README.md` (1 ref)
- `docs/wiki/getting-started.md` (1 ref)

### P3: Implementation guides & drafts (add superseded notes or update)
- `docs/impl/RFC-0008-configuration-guide.md`
- `docs/drafts/` (mark superseded)
- `docs/impl/IG-074-final-summary.md`, `IG-097-layer2-loopagent-implementation.md` (add superseded notes)
