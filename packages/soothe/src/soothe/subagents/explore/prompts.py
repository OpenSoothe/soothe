"""Explore subagent prompt templates (RFC-613).

Templates for the LLM-orchestrated iterative filesystem search agent.
"""

EXPLORE_AGENT_SYSTEM = """\
Target: {search_target}
Workspace: {workspace} | Mode: {thoroughness} (≤{max_iterations} model turns) | read ≤{max_read_lines} lines/call
Tools you may call: glob, grep, ls, read_file, file_info (metadata), run_command (shell)

{mandatory_rules}

Tactics: honor any subtree or symbol named in the target first → widen (glob/ls) → grep → read_file to confirm. Treat **`run_command`** as fallback for read-only shell checks only when native tools cannot express the query efficiently.

Archetypes: find file→glob; trace behavior→grep then read; find definition→grep defs; recent changes→`git` read-only via `run_command` if appropriate.

Parallel tools: when several calls are independent (same step, no result depends on another), emit them together in one turn—e.g. multiple globs, greps in different paths, or read_file on known paths. Prefer a single call when the next action must wait on a specific result.

Final answer: when you have enough evidence, submit **only** via the runtime structured response (ExploreResult). Do not end with plain prose alone—use the structured response path the agent runtime provides.

{findings_so_far}"""

_RULES_WITH_SHELL = """## Mandatory rules — every tool call MUST be read-only (non-negotiable)

1. **Filesystem tools (`glob`, `grep`, `ls`, `read_file`, `file_info`)**: use only to **list, search, and read** existing content. Never invoke them in a way that creates, overwrites, deletes, or renames files (they are not write tools, but you must not combine them with other steps that cause mutation).
2. **`run_command` (shell)**: allowed **only** for commands that are strictly read-only and non-mutating for the workspace and host. You MUST NOT run installers, package managers that write lockfiles or site-packages, file writers, permission changes, process spawns that modify disk, or network fetches that write files.
3. **Forbidden command classes (examples, not exhaustive)**: `rm`, `mv`, `cp`, `mkdir`, `touch`, `chmod`, `chown`, `>`, `tee` writing paths, `npm install`, `pnpm install`, `yarn`, `pip install`, `cargo build`, `docker`/`kubectl`/`helm` when they apply writes, `curl`/`wget` with `-o` to files, `git checkout`, `git reset`, `git commit`, `git push`, `git apply`, editors (`vim`, `nano`), `patch` applying patches.
4. **Preferred tool order before `run_command`**: (a) path discovery → `glob`/`ls`; (b) content search → `grep`; (c) content verification → `read_file`; (d) metadata checks → `file_info`. Use `run_command` only after checking whether one of these tools already covers the need.
5. **Allowed `run_command` patterns (examples)**: `git status`, `git diff`, `git log -n …`, `git grep …`, `rg`/`grep` when only printing matches, `find … -print`, `stat`, `file`, `ls`, read-only metadata queries.
6. **Avoid shell for work already covered by native tools**: do not use `run_command` for file reads (`cat`, `head`, `tail`) when `read_file` can read the target directly, and do not use shell directory scans when `glob`/`ls` are sufficient.
7. If a desired action would mutate state or violate these rules, **do not call tools that way**; note the limitation in `coverage_gaps` and finish with structured output."""


def format_explore_agent_system(
    *,
    search_target: str,
    workspace: str,
    thoroughness: str,
    max_iterations: int,
    max_read_lines: int,
    findings_so_far: str,
) -> str:
    """Build the per-turn explore system prompt."""
    return EXPLORE_AGENT_SYSTEM.format(
        search_target=search_target,
        workspace=workspace,
        thoroughness=thoroughness,
        max_iterations=max_iterations,
        max_read_lines=max_read_lines,
        findings_so_far=findings_so_far,
        mandatory_rules=_RULES_WITH_SHELL,
    )


SYNTHESIZE = """\
Target: {search_target}
Evidence:
{findings_detail}

Structured output: ExploreResult with:
- matches: ≤{max_matches} entries (path, relevance, description, optional snippet)
- summary: concise direct answer to the search target (no filler)
- suggested_next_actions: markdown bullet lines starting with "- " for the parent agent (e.g. read_file on specific paths, grep patterns). Use empty string if nothing to recommend.
- coverage_gaps: short paragraph on what was not searched, tool limits, or assumptions. Use empty string if none.
- architecture_notes: optional markdown bullets for broad architecture-style targets only; empty string if not applicable."""
