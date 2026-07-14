# IG-415: Optional heavy delegated agents in soothe-community

**Status**: Implemented  
**Created**: 2026-05-15  
**Depends on**: RFC-600 (plugin system), RFC-601 split (community agents)

## Goal

Move optional, dependency-heavy delegated-agent implementations out of the core `soothe` wheel into **`soothe-community`**, keep core discovery limited to first-party agents, and document install and configuration only in the community repository.

## Notes

- Curated wire event type prefixes under `soothe.subagent.*` remain stable for clients; payloads stay allowlisted per IG-339.
- Core resolver may still apply model wiring exceptions for specific manifest ids when plugins register them; see `packages/soothe/src/soothe/core/resolver/_resolver_tools.py`.
- End-user install, extras, slash routing for optional agents, and YAML examples live in **`soothe-community`** only.

## Verification

```bash
./scripts/verify_finally.sh
```

## Files touched (summary)

| Area | Path |
|------|------|
| Community plugins | `community/src/soothe_community/`, `community/pyproject.toml` |
| Core discovery/resolver/config | `packages/soothe/src/soothe/plugin/discovery.py`, `.../resolver/_resolver_tools.py`, `.../config/*`, `config/config.template.yml` |
| SDK | `packages/soothe-sdk/src/soothe_sdk/core/subagent_wire.py` |
| Daemon | `packages/soothe-daemon/.../message_router.py` |
