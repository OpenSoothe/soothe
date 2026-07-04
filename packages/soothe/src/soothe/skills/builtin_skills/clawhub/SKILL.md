---
name: clawhub
description: Search and install agent skills from ClawHub (public skill registry). Use when the user wants to find, install, update, or list community skills for the current Soothe workspace.
tags: clawhub, claw hub, skill registry, install skill, community skills
metadata: {"emoji":"🦞","requires":{"bins":["npx"]}}
---

# ClawHub

Public skill registry for AI agents. Search by natural language (vector search); install versioned `SKILL.md` packages.

## When to use

Use this skill when the user asks to:

- find or search for a skill ("skill for …", "anything on ClawHub for …")
- install, update, or uninstall a registry skill
- list what is already installed
- publish or sync skills (needs `clawhub login`)

## Install location (Soothe)

**Default for Soothe:** install into the **active workspace**, not the shell cwd alone.

| Target | ClawHub flags | Soothe discovery |
|--------|---------------|------------------|
| **Project (preferred)** | `--workdir <workspace> --dir .soothe/skills` | `<workspace>/.soothe/skills/<slug>/` |
| **User-wide** | `--workdir ~/.soothe` (default `--dir skills`) | `~/.soothe/skills/<slug>/` |

Soothe loads skills from (in order): bundled `built_in_skills`, then `~/.agents/skills`, `~/.soothe/skills`, and **`<workspace>/.soothe/skills`** when a workspace is set for the run.

**Resolve `<workspace>` before every install/update/list:**

1. The workspace path from the current Soothe session / loop (preferred).
2. Else the user's project root (git root or explicit project directory).
3. Else `SOOTHE_WORKSPACE` if set.
4. Do **not** use bare cwd unless it is known to be the Soothe workspace.

Set once per shell session:

```bash
WORKSPACE="/path/to/project"   # absolute path to Soothe workspace root
CLAWHUB_FLAGS="--workdir ${WORKSPACE} --dir .soothe/skills"
```

Upstream ClawHub defaults to `./skills` under `--workdir`; Soothe expects **`.soothe/skills`**, so always pass `--dir .soothe/skills` for workspace installs.

## Search

```bash
npx --yes clawhub@latest search "web scraping" --limit 5
```

Browse newest:

```bash
npx --yes clawhub@latest explore --limit 10
```

Inspect without installing:

```bash
npx --yes clawhub@latest inspect <slug>
```

## Install

```bash
npx --yes clawhub@latest install <slug> ${CLAWHUB_FLAGS}
```

Examples:

```bash
WORKSPACE="$(pwd)"   # only when pwd is the Soothe workspace root
npx --yes clawhub@latest install weather ${CLAWHUB_FLAGS}
# → ${WORKSPACE}/.soothe/skills/weather/
```

Overwrite an existing folder:

```bash
npx --yes clawhub@latest install <slug> ${CLAWHUB_FLAGS} --force
```

**User-wide install** (all projects):

```bash
npx --yes clawhub@latest install <slug> --workdir ~/.soothe
# → ~/.soothe/skills/<slug>/
```

## Update / list / uninstall

```bash
npx --yes clawhub@latest update --all ${CLAWHUB_FLAGS}
npx --yes clawhub@latest list ${CLAWHUB_FLAGS}
npx --yes clawhub@latest uninstall <slug> ${CLAWHUB_FLAGS} --yes
```

Pinned skills are skipped by `update --all`; run `clawhub unpin <slug>` first if the user wants to refresh them.

## Publish (optional)

Publishing requires login:

```bash
npx --yes clawhub@latest login
npx --yes clawhub@latest skill publish ./my-skill --version 1.0.0
```

## Notes

- Requires Node.js (`npx` ships with it). No API key for search/install.
- `CLAWHUB_WORKDIR` can replace `--workdir`; you still need `--dir .soothe/skills` for workspace layout unless using `~/.soothe`.
- Lock/metadata: `<workdir>/.soothe/skills/.clawhub/` (or legacy `.clawdhub`).
- After install or update, tell the user to **start a new Soothe session** (or restart the daemon loop) so skill metadata reloads.
- If install succeeded but the skill does not appear, verify the path is under `<workspace>/.soothe/skills/<slug>/SKILL.md` and that `WORKSPACE` matches the session workspace.
