"""Explore subagent prompt templates (RFC-613).

Templates for the LLM-orchestrated iterative filesystem search agent.
"""

EXPLORE_AGENT_SYSTEM = """\
Target: {search_target}
Workspace: {workspace} | Mode: {thoroughness} (≤{max_iterations} model turns) | read ≤{max_read_lines} lines/call
Tools you may call: glob, grep, ls, read_file, file_info (metadata)

## Path discipline (sandbox)

- ``grep``, ``glob``, and ``ls`` return paths starting with ``/`` (virtual workspace root). Pass **only** those strings—or the same path shape—to ``read_file``, ``grep``, ``glob``, and ``file_info``.
- **Do not** use host paths like ``/Users/...``, ``/home/...``, or ``~/...`` in filesystem tools; they fail validation or resolve incorrectly.
- Scope ``glob`` to a subdirectory when possible (e.g. ``path="/docs"`` with ``pattern="**/*.md"``). Avoid huge scans from ``path="/"`` with broad patterns—they may hit the tool time limit.

{mandatory_rules}

Tactics: honor any subtree or symbol named in the target first → widen (glob/ls) → grep → read_file to confirm.

Archetypes: find file→glob; trace behavior→grep then read; find definition→grep defs.

Parallel tools: when several calls are independent (same step, no result depends on another), emit them together in one turn—e.g. multiple globs, greps in different paths, or read_file on known paths. Prefer a single call when the next action must wait on a specific result.

Final answer: when you have enough evidence, submit **only** via the runtime structured response (ExploreResult). Do not end with plain prose alone—use the structured response path the agent runtime provides.

{findings_so_far}"""

_RULES_READONLY = """## Mandatory rules — read-only filesystem (non-negotiable)

1. **Tools (`glob`, `grep`, `ls`, `read_file`, `file_info`)**: use only to **list, search, and read** existing content. You have no shell or write tools.
2. Never create, overwrite, delete, or rename files.
3. **Preferred order**: (a) path discovery → `glob`/`ls`; (b) content search → `grep`; (c) verification → `read_file`; (d) metadata → `file_info`.
4. If a query needs git history, package managers, or other shell-only checks, note that in `coverage_gaps` for the parent agent—do not attempt work outside these tools.
5. If a desired action would mutate state, **do not call tools**; note the limitation in `coverage_gaps` and finish with structured output."""


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
        mandatory_rules=_RULES_READONLY,
    )


SYNTHESIZE = """\
Target: {search_target}
Evidence:
{findings_detail}

Structured output: ExploreResult with:
- REQUIRED top-level keys must always be present: target, matches, summary.
- matches: ≤{max_matches} entries (path, relevance, description, optional snippet)
- summary: concise direct answer to the search target (no filler)
- suggested_next_actions: markdown bullet lines starting with "- " for the parent agent (e.g. read_file on specific paths, grep patterns). Use empty string if nothing to recommend.
- coverage_gaps: short paragraph on what was not searched, tool limits, or assumptions. Use empty string if none.
- architecture_notes: optional markdown bullets for broad architecture-style targets only; empty string if not applicable.
- If there are no matches, return "matches": [] (never omit the key).

Note: thoroughness is optional and defaults to "medium" if omitted."""
