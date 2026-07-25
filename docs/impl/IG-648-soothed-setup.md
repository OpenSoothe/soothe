# IG-648: `soothed setup` — Config Scaffold + Provider Wizard

**Status**: Implemented  
**Related**: IG-631 (config layout), RFC-000

## Goal

Add `soothed setup` to create `$SOOTHE_HOME/config/{nano,soothe,daemon}.yml` from templates and interactively configure the only required values: LLM provider endpoint, API key, and default router model.

## Required vs defaults

| File | User input | Defaults OK |
|------|------------|-------------|
| `nano.yml` | `api_base_url`, `api_key` (or env), `router.default` | tools, sqlite, embedding, security, middleware |
| `soothe.yml` | none (v1) | StrangeLoop, autopilot off, cron |
| `daemon.yml` | none (v1) | `127.0.0.1:8765`, identity off |

## Phases

1. Ensure config dir  
2. Scaffold missing YAMLs from packaged templates (atomic write)  
3. Interactive nano provider (fj-like; soft-fail model fetch → manual id)  
4. Validate Pydantic load  
5. Optional doctor providers check (warning only)

## Fault tolerance

- Scaffold before mutate; cancel mid-wizard leaves skeleton  
- Never overwrite existing files without `--force`  
- Secrets prefer `${ENV}` + `$SOOTHE_HOME/.env`  
- `--yes` non-interactive scaffold (+ env bootstrap merge)  
- Re-run skips scaffold, re-enters provider wizard  

## CLI

```text
soothed setup [--config-dir PATH] [--yes] [--force] [--skip-provider] [--skip-doctor]
```

## Package

`packages/soothe-daemon/src/soothe_daemon/setup/`
