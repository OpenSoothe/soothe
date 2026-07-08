# Skill Runtime Discovery

**Status**: Approved (Platonic handoff → RFC-105 revision + IG-543)  
**Date**: 2026-07-03  
**Kind**: Design  
**Related**: RFC-105 (Progressive Skill Loading), RFC-412 (MCP progressive disclosure — parity pattern), IG-519 (middleware caching)  
**Supersedes behavior in**: RFC-105 unconditional/conditional partition; turn-0 listing of all skills without `paths:`  

---

## 1. Problem

RFC-105 P0 shipped three disjoint discovery channels:

| Channel | Trigger | Limit |
|---------|---------|-------|
| Unconditional listing | Turn 0 | Scales with catalog size |
| `paths:` + file-op | Implicit | Only on file touch |
| `/skill:name` | Human/CLI | No model-first-class tool |

Large skill catalogs still pay turn-0 cost for every skill without `paths:`. The model has `search_tools` but no `search_skills`. Skillify semantic search is a separate plugin, not wired into progressive state.

---

## 2. Design principles

1. **One catalog, two tiers** — `core` (always listed) vs `deferred` (hidden until discovered).
2. **One state machine** — discover → list (metadata delta) → load (full body).
3. **Two discovery channels** — path hook (implicit) + `search_skills` (intent, model-driven).
4. **Parity with tools** — same mental model as `progressive_tools` + `search_tools`.
5. **Minimal diff** — extend RFC-105 components; do not add a new loop concept.

---

## 3. Catalog partition

### Frontmatter

```yaml
---
name: python-helper
description: Python patterns for this repo
core: false          # optional; default false for user skills, true for built-ins
paths:               # optional; auto-discovery on file-op (deferred only)
  - "src/**/*.py"
---
```

| Tier | Rule | Turn 0 |
|------|------|--------|
| **Core** | `source == builtin` (unless `core: false`), or `core: true`, or name in `progressive_skills.core_skills` | Listed in `<AVAILABLE_SKILLS>` (budgeted) |
| **Deferred** | Everything else | Hidden until discovered |

`paths:` does **not** promote a skill to core. It registers an auto-discovery rule on deferred skills.

---

## 4. Runtime state

Graph state `skill_activation` (LoopState field names unchanged for durability):

```python
{
    "sent": set[str],              # already in AVAILABLE_SKILLS
    "activated": set[str],         # discovered (path, search, or explicit) — RFC alias: "discovered"
    "invoked": set[str],           # body loaded into context
    "invoked_bodies": dict[str, str],
    "just_invoked": set[str],      # transient dedup for current turn
}
```

Single mutation for all discovery channels:

```python
registry.discover(activation_state, names, via="path" | "search" | "explicit")
# → updates activated set; emits SkillDiscoveredEvent (internal)
```

---

## 5. Discovery channels

### A. Path hook (implicit, unchanged semantics)

On file-op tools, match deferred skills with `paths:` → `discover(..., via="path")`.  
Metadata appears in `<AVAILABLE_SKILLS>` on the **next** hop.

### B. `search_skills` tool (new)

```python
search_skills(query: str, limit: int = 5) -> str
```

- Search deferred skills not yet in `activated`.
- Substring match on `name`, `description`, `tags` (P0).
- `discover(matches, via="search")`.
- Return discovered names; metadata on next hop; use `invoke_skill` to load body.

Core skills are never searchable — already visible.

### C. `invoke_skill` tool (new)

```python
invoke_skill(name: str, args: str = "") -> str
```

- Resolve skill, read SKILL.md once, `mark_invoked`.
- Body in `<SKILL_CONTEXT>` on subsequent hops (same as `/skill:`).
- `/skill:` CLI path unchanged; calls same load helper.

---

## 6. Prompt assembly

```
candidates = core_skills ∪ activated
new = candidates - sent
→ format within budget → <AVAILABLE_SKILLS>
→ mark_sent(new)

for name in invoked - just_invoked:
→ <SKILL_CONTEXT> from invoked_bodies
```

System prompt hint (static tier):

> Deferred skills are hidden. Use `search_skills(query)` to find capabilities, then `invoke_skill(name)` to load instructions. Skills may also auto-appear when you touch matching files.

---

## 7. Config

```yaml
progressive_skills:
  budget_pct: 0.01
  max_listing_chars_per_entry: 250
  min_listing_chars_per_entry: 20
  core_skills: null              # null → built-in defaults
  search_skills_enabled: true
```

---

## 8. Non-goals (P0)

- Skillify as default search backend (P1 follow-on).
- Turn-0 intent prefetch from user goal (P2).
- Renaming LoopState snapshot fields (`activated_skill_names` kept; means "discovered").
- MCP-provided skills.

---

## 9. Verification

- Unit: `partition_core_deferred`, `search_deferred`, `discover`, middleware handlers.
- Integration: turn-0 lists only core; `search_skills` discovers deferred; `invoke_skill` loads body.
- `./scripts/verify_finally.sh` passes.

---

## 10. Handoff

| Artifact | Action |
|----------|--------|
| RFC-105 | Revise §Architecture, §Type Definitions, §API Contracts |
| IG-543 | Implementation guide |
| Code | P0 in `registry`, `skill_activation`, `system_prompt`, agent builder, config |
