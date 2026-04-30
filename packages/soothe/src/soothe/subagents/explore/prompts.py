"""Explore subagent prompt templates (RFC-613).

Templates for the LLM-orchestrated iterative filesystem search agent.
"""

PLAN_SEARCH = """\
Target: {search_target}
Workspace: {workspace} | Mode: {thoroughness} (≤{max_iterations} iters) | read ≤{max_read_lines} lines/call
Tools (readonly): glob, grep, ls, read_file, file_info

Tactics: honor any subtree or symbol named in the target first → widen (glob/ls) → grep → read_file to confirm.
Archetypes: find file→glob; trace behavior→grep then read; find definition→grep defs.

{findings_so_far}
One tool call next."""

ASSESS_RESULTS = """\
Target: {search_target}
Findings: {findings_summary}
Used: {iterations_used}/{max_iterations}

decision must be exactly one of: continue | adjust | finish (structured output)."""

SYNTHESIZE = """\
Target: {search_target}
Evidence:
{findings_detail}

Structured output: ExploreResult with matches (≤{max_matches}, path/relevance/description/snippet) and summary."""
