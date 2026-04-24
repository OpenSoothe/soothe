# IG-169: Remember built-in skill and TUI skill loader

## Status

Completed (verification: `./scripts/verify_finally.sh`).

## Goal

- **Note**: This IG originally planned to ship a built-in `remember` skill under `src/soothe/skills/remember/`, but that folder structure was removed during the monorepo migration. The TUI skills functionality was implemented in `packages/soothe-cli/src/soothe_cli/tui/skills/` instead.
- Replace stubbed `soothe.ux.tui.skills.load` / `soothe.ux.tui.skills.invocation` with real discovery, containment checks, and prompt envelopes aligned with `SootheApp._invoke_skill`.

## Scope

- Implement skill directory scanning (built-in package skills, per-agent `SOOTHE_HOME` skills, project `.soothe/skills`, optional `.agents` / `.claude` bridge dirs).
- `load_skill_content(path, allowed_roots=...)` with path containment.
- `build_skill_invocation_envelope(cached, content, args)` returning `prompt` + optional `message_kwargs`.
- Unit tests for discovery and containment.

**Note**: The `remember/SKILL.md` file under `src/soothe/skills/` was not created as that folder structure was removed. The skill concept remains documented for reference.

## Non-goals

- Changing daemon or headless slash-command handling beyond what already routes `/remember` in the TUI app.
- Porting deepagents-cli verbatim; behavior is informed by the migration notes (IG-166) and Soothe patterns only.

## Verification

Run `./scripts/verify_finally.sh` before merge.
