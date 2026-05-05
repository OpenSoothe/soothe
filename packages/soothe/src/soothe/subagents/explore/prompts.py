"""Explore subagent prompt templates (RFC-613).

Templates for the LLM-orchestrated iterative filesystem search agent.
"""

PLAN_SEARCH = """\
Target: {search_target}
Workspace: {workspace} | Mode: {thoroughness} (≤{max_iterations} iters) | read ≤{max_read_lines} lines/call
Tools (readonly): glob, grep, ls, read_file, file_info (metadata)

Tactics: honor any subtree or symbol named in the target first → widen (glob/ls) → grep → read_file to confirm.
Archetypes: find file→glob; trace behavior→grep then read; find definition→grep defs.

Parallel tools: when several calls are independent (same step, no result depends on another), emit them together in one turn—e.g. multiple globs, greps in different paths, or read_file on known paths. Prefer a single call when the next action must wait on a specific result.

{findings_so_far}
Plan the next tool call(s) for this step."""

ASSESS_RESULTS = """\
Target: {search_target}
Findings: {findings_summary}
Used: {iterations_used}/{max_iterations}

decision must be exactly one of: continue | adjust | finish (structured output)."""

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
