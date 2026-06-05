# Soothe Builtin Skills

This directory contains builtin skills that ship with Soothe. Skills are self-contained packages that extend the agent's capabilities with specialized knowledge, workflows, and tools.

## Available Skills

| Skill | Purpose | Dependencies |
|-------|---------|--------------|
| **weather** | Get current weather and forecasts (no API key required) | curl |
| **github** | Interact with GitHub via `gh` CLI | gh |
| **clawhub** | Search and install skills from ClawHub registry | Node.js/npx |
| **skill-creator** | Create and package new AgentSkills | None |

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

Quick start (project workspace — preferred):
```bash
WORKSPACE="$(pwd)"   # Soothe workspace root
SKILLS_DIR="${WORKSPACE}/.soothe/skills"
mkdir -p "${SKILLS_DIR}"

# Initialize a new skill
python packages/soothe/src/soothe/built_in_skills/skill-creator/scripts/init_skill.py \
  my-skill --path "${SKILLS_DIR}"

# Edit the SKILL.md
cd "${SKILLS_DIR}/my-skill"
# Edit SKILL.md...

# Package the skill
python packages/soothe/src/soothe/built_in_skills/skill-creator/scripts/package_skill.py \
  "${SKILLS_DIR}/my-skill"
```

User-wide install: use `--path ~/.soothe/skills` instead of `${SKILLS_DIR}`.

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

These are documented in each skill's metadata for graceful degradation.