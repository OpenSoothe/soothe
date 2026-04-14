# Soothe Builtin Skills

This directory contains builtin skills that ship with Soothe. Skills are self-contained packages that extend the agent's capabilities with specialized knowledge, workflows, and tools.

## Available Skills

| Skill | Purpose | Dependencies |
|-------|---------|--------------|
| **create-subagent** | Guide for creating new subagents (SubAgent vs CompiledSubAgent) | None |
| **weather** | Get current weather and forecasts (no API key required) | curl |
| **github** | Interact with GitHub via `gh` CLI | gh |
| **tmux** | Remote-control tmux sessions for interactive CLIs | tmux |
| **summarize** | Summarize URLs, files, YouTube videos | summarize CLI |
| **cron** | Schedule reminders and recurring tasks | cron tool |
| **clawhub** | Search and install skills from ClawHub registry | Node.js/npx |
| **skill-creator** | Create and package new AgentSkills | None |
| **remember** | Persist session learnings into memory / `AGENTS.md` / skills via tools | None |

## Skill Format

Each skill follows the AgentSkills specification:

```
skill-name/
├── SKILL.md          # Required: YAML frontmatter + instructions
├── scripts/          # Optional: Executable helper scripts
├── references/       # Optional: Documentation loaded as needed
└── assets/           # Optional: Templates, resources
```

## Discovery

Builtin skills are automatically discovered by `get_built_in_skills_paths()` in `__init__.py`. User skills can be added via `SootheConfig.skills`:

```python
from soothe.config import SootheConfig

config = SootheConfig(
    skills=["~/.soothe/skills/", "/path/to/custom/skills/"]
)
```

## Creating New Skills

See the `skill-creator` skill for comprehensive guidance on creating new skills.

Quick start:
```bash
# Initialize a new skill
python src/soothe/skills/skill-creator/scripts/init_skill.py my-skill --path ~/.soothe/skills

# Edit the SKILL.md
cd ~/.soothe/skills/my-skill
# Edit SKILL.md...

# Package the skill
python src/soothe/skills/skill-creator/scripts/package_skill.py ~/.soothe/skills/my-skill
```

## Progressive Disclosure

Skills use a three-level loading system:
1. **Metadata** (name + description) - Always loaded (~100 words)
2. **SKILL.md body** - Loaded when skill triggers (<5k words)
3. **Bundled resources** - Loaded as needed

This keeps context lean while providing unlimited depth when needed.

## External Dependencies

Some skills require external CLI tools:

| Skill | Tool | Install |
|-------|------|---------|
| github | `gh` | `brew install gh` or `apt install gh` |
| tmux | `tmux` | `brew install tmux` or `apt install tmux` |
| summarize | `summarize` | `brew install steipete/tap/summarize` |

These are documented in each skill's metadata for graceful degradation.