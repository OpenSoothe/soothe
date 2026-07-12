# IG-639: Remove deepagents execute tool

**Status:** Complete

## Goal

Remove deepagents sandbox `execute` from Soothe entirely; host execution tools are the only shell path.

## Changes

- Always strip `execute` from resolver tools and patch `FilesystemMiddleware` init.
- Remove `security.sandbox` config knob.
- Register `run_command` in SDK metadata (legacy `shell`/`bash` aliases).

## Verification

- `./scripts/verify_finally.sh`
