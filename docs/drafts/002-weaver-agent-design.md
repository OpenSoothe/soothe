Here is the design of Weaver subagent in Soothe.

## Purpose

Weaver is a framework of generative agents from Skills, tools or MCP. It generates INSTANT subagents compabitle with Soothe framework from user request.

For example, when user requests "find ArXiv paper during last week on Agent Memory and extract their paper profiles and main contributions".

Weaver would do following things:
- Call Skillify agent to fetch related Skills
- Find available tools and MCPs
- Call bundled `create-subagent` skill to create a new subagent which could be loaded by Soothe.
- Then the generated agent could be called by Soothe to response user request.

## Arch

### Soothe and Subagent Skill layout

In Soothe, each subagent has its own working directory under `~/.soothe/agents/<agent_name>/`

```bash
# Soothe main working dir
~/.soothe
# Soothe skills repo
~/.soothe/skills
# Weaver
~/.soothe/agents/weaver/skills/create-subagent/
# Soothe generated subagents
~/.soothe/agents/gened-<agent_name>/
~/.soothe/agents/gened-<agent_name>/skills/
```

### Arch design

Weaver also maintains a file or semantic based indexing of generated agents, which could be used by Soothe to find already generated agents for new requests, or to generate a new one.

