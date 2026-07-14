# IG-654: Deep Research Subagent (Phase 1)

**Status**: Complete  
**RFC**: RFC-619 (revised 2026-07-07)  
**Branch**: `feat/opt-deep-research`

## Scope

Replace the prior monolithic research subagent with `deep_research`: web-only iterative research, crawl-on-discovery, adaptive report, clean break.

## Tasks

- [x] RFC-619 revised
- [x] `toolkits/url_crawl/` shared crawl + polite HTTP
- [x] `subagents/deep_research/` package
- [x] Delete prior `subagents/` monolithic research package
- [x] Resolver, config, CLI slash, events, tests — rename to `deep_research`
- [x] `./scripts/verify_finally.sh`

## Out of scope (phase 2)

`academic_research` subagent
