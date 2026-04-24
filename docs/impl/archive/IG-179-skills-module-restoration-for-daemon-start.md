# IG-179 Skills Module Restoration For Daemon Start

## Goal

Restore `soothe.skills` so daemon startup does not fail with `ModuleNotFoundError`.

## Problem

`soothe.core.agent._builder` imports:

- `from soothe.skills import get_built_in_skills_paths`

But `soothe.skills` is missing, which causes `soothe-daemon start` to fail before runtime initialization completes.

## Scope

- Add `packages/soothe/src/soothe/skills.py`.
- Provide built-in skill directories under the soothe package for baseline availability.

## Design

1. `get_built_in_skills_paths()` returns absolute skill directory paths that contain `SKILL.md`.
2. It searches:
   - Package-bundled built-ins (`soothe/built_in_skills/`).
   - User skill locations (`~/.cursor/skills-cursor`, `~/.cursor/skills`, `~/.claude/skills`).
3. Paths are de-duplicated and stable-sorted.
4. Add baseline built-ins:
   - `create-subagent`
   - `remember`

## Validation

- Run `soothe-daemon start --foreground` to verify startup passes import phase.
- Run `soothe-daemon doctor --fail-on error`.
- Run focused unit tests for daemon CLI and built-in skill discovery.
