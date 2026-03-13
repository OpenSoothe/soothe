Here is the design of Skillify subagent in Soothe.

## Purpose

Skillify agent performs skills management at sementic level, including crawling skills from Internet, storing skills for reuse by other agents, semantic indexing and searching.

## Arch

Skillify is standalone and self-contained. It would call other subagents for specific purposes, e.g., browser agent for surfing Internet, claude agent to perform coding to process parsed data.

Skillify is architectually compatible with Soothe framework. It has two main standalone but related purposes. One is an infinite loop to perform skills collecting (crawling, storing, indexing) and maintain the skills repo. The other is serving semantic skill fetching when user requests arrive to get a bunch of skills to use.

For the first purpose, the raw skills are saved in the file system (a configurable location such as `~/.soothe/agents/skillify/warehouse/`). The semantic indexing is served via vector store (based on Soothe Vector store).

For the second purpose, user usually sends a request, e.g., "process images and extract people faces and segment faces from the image". Then Skillify would search the Skill database and return a set of skills for users.

When Skillify calls other agents, such as Browser, the BrowserAgent's temp data are saved under skillify work dir, i.e., `~/.soothe/agents/skillify/` subdirectories.