Here is the design of Weaver subagent in Soothe.

## Purpose

Weaver is a framework of generative agents from Skills, tools or MCP.

Weaver introduces a concept of INSTANT or SNAP agents, what are created for ad-hoc user purpose which are not fulfilled by built-in or bundled Soothe subagents. Weaver generates INSTANT subagents compabitle with Soothe framework from user request.

For example, when user requests "find ArXiv paper during last week on Agent Memory and extract their paper profiles and main contributions".

Weaver would do following things:
- Call Skillify agent to fetch related Skills (returned a set of Skill paths)
- Find related tools and MCPs that are available
- Call bundled `create-subagent` skill (soothe/skills/create-subagent) to create a new subagent which could be loaded by Soothe.
- The fetched skills from Skillify would be COPY into <generate_agent_name>/skills/
- Then the generated agent could be loaded dynamically and called by Soothe to response user request.
- The generated agents in future would be reused by Soothe in future, the same as built-in subagents.
- Before a new subagent is to created, Weaver check exiting built-in and previously generated ones to REFLECT if there is already one to fulfill user request. Otherwise, create a new one.

## Arch

### Soothe and Subagent Skill layout

Here is Soothe workdir and generated agents location:

```bash
# Soothe main working dir
~/.soothe

# Soothe skills repo
~/.soothe/skills

# Soothe built-in agents workdir
~/.soothe/agents/<agent_name>/

# Soothe weaved agents
~/.soothe/generated_agents/<agent_name>/

# The generated agents could have their own skills or other source code
~/.soothe/generated_agents/<agent_name>/skills/
```
