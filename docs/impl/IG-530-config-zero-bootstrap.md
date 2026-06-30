# IG-530: Config Zero-Bootstrap and Slim Template

**Status:** In progress  
**Design:** `docs/drafts/2026-06-30-config-zero-bootstrap-design.md`

## Scope

- Env-first provider bootstrap when `providers` is empty (`OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `OPENAI_BASE_URL`)
- Code defaults for vector stores (`default_vector_stores`, `default_vector_store_router`)
- Slim `config/config.template.yml` to Tier A/B only (~80 lines)
- Tests + README/wiki updates

## Checklist

- [x] `default_vector_stores()` / `default_vector_store_router()` in `settings.py`
- [x] `_bootstrap_providers_from_env` validator
- [x] Slim `config.template.yml`
- [x] Unit tests (`TestEnvProviderBootstrap`, template regression)
- [x] README + wiki configuration guide
- [x] `./scripts/verify_finally.sh`

## Notes

- Explicit YAML `providers` always wins over env bootstrap.
- Anthropic-only bootstrap patches default router profile to `anthropic:claude-sonnet-4-20250514`.
- `config/develop/config.yml` unchanged in behavior (team overrides only).
