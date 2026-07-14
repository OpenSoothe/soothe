# IG-319: Increase default LLM call timeout

## Problem

Some goal-completion synthesis calls exceed the current default LLM timeout floor (`60s`) and can fail with `TimeoutError` before a final response is produced.

## Solution

1. Increase the default execution timeout floor from `60s` to `120s`.
2. Increase the adaptive timeout cap from `600s` to `900s`.
3. Keep config defaults synchronized across:
   - `packages/soothe/src/soothe/config/models.py`
   - `packages/soothe/src/soothe/config/config.yml`
   - `config/config.dev.yml`

## Verification

- Run `./scripts/verify_finally.sh`
