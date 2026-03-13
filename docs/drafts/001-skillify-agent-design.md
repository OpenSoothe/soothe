Here is the design of Skillify subagent in Soothe.

## Purpose

Skillify agent performs skills management at sementic level, including semantic indexing and searching, and response to user request with matched skills. Given a warehouse of agentic skills that are read-only for Skillify, Skillify would index, search and use skills.

## Arch

Skillify is standalone and self-contained, which is architectually compatible with Soothe framework.

Skillify DO NOT care about how the skill warehouse is created and managed. It is only one user of the warehouse.

It has two main standalone but connected funcionalities. One is an infinite loop to perform skills semantic indexing. The other is serving user requests to get a bunch of skills to use via semantic skill fetching.

For the first purpose, the skill warehouse is configurable by user (or default `~/.soothe/agents/skillify/warehouse/`). The skill MUST comply with and could be loaded by deepagent's SkillMiddleware. The semantic indexing is served via vector store (based on Soothe Vector store).

For the second purpose, user usually sends a request, e.g., "process images and extract people faces and segment faces from the image". Then Skillify would search the Skill warehouse and return a set of skills (paths directing to skills location) for users.

Skillify is built using LangGraph and as a subagent of Soothe.