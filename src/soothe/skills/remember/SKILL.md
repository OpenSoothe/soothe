---
name: remember
description: Capture durable facts, preferences, and procedures from the chat into memory and project docs (AGENTS.md / skills) using available tools.
---

# Remember

Use this skill when the user wants to **persist learnings** from the current session: stable preferences, recurring workflows, project conventions, API quirks, debugging recipes, or anything that should survive a new thread.

## What to do

1. **Clarify scope** (briefly): infer from the user message and recent turns what should be remembered. If the user gave explicit text in `/remember ...`, treat that as the primary source of truth.
2. **Prefer existing mechanisms** (Soothe / deepagents ecosystem — do not invent parallel stores):
   - **Memory**: If a memory tool or protocol-backed memory is available, store concise, retrieval-oriented notes (atomic facts, labeled with topic). Avoid dumping entire transcripts.
   - **Project docs**: When the user wants team-visible or repo-local knowledge, update or create **`AGENTS.md`** (or an existing project skill under `.soothe/skills/` / configured skill dirs) with short, actionable bullets — not essays.
   - **New reusable skill**: Only when the user asks for a packaged workflow (steps + guardrails + optional scripts). Otherwise prefer memory + AGENTS.md.
3. **Be conservative**: Do not store secrets (tokens, passwords), one-off debug noise, or legally sensitive content unless the user clearly asked and it is safe.
4. **Confirm briefly** in natural language what you updated (which artifact: memory entry, file path, or new skill) and one-sentence why it will help next time.

## What not to do

- Do not replace normal assistant answers — this skill is for **persistence**, not for re-answering the last question.
- Do not create large new markdown files unless the user asked for documentation or a skill package.

## Empty `/remember`

If the user ran `/remember` with no extra text, **infer** 3–7 high-signal bullets from the visible conversation worth remembering, then persist them as above.
