"""Progress event rendering for CLI output."""

import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from soothe.cli.progress_verbosity import ProgressVerbosity

_MAX_INLINE_QUERIES = 3


def render_progress_event(
    data: dict,
    *,
    prefix: str | None = None,
    verbosity: "ProgressVerbosity" = "normal",
) -> None:
    """Render a soothe.* event as a structured progress line to stderr."""
    etype = data.get("type", "")
    if etype.startswith("soothe."):
        tag = etype.replace("soothe.", "").split(".")[0] if "." in etype else "soothe"
    elif "." in etype:
        tag = etype.split(".")[0]
    elif etype:
        tag = etype.split("_")[0]
    else:
        tag = "custom"
    parts: list[str] = []

    # Main agent tool events
    if etype.startswith("soothe.tool.") and ".started" in etype:
        tool = data.get("tool", "?")
        parts = [f"Calling: {tool}"]
        sys.stderr.write("\n")
    elif etype.startswith("soothe.tool.") and ".completed" in etype:
        tool = data.get("tool", "?")
        result_preview = str(data.get("result_preview", ""))[:60]
        parts = [f"Result ({tool}): {result_preview}"]
    elif etype.startswith("soothe.tool.") and ".failed" in etype:
        tool = data.get("tool", "?")
        error = data.get("error", "unknown error")
        parts = [f"Error ({tool}): {str(error)[:60]}"]
    # Tool activity events
    if etype == "soothe.tool.search.started":
        query = data.get("query", "")
        engines = data.get("engines", [])
        parts = ["Searching:", str(query)[:40]]
        if engines:
            parts.append(f"({', '.join(engines[:3])})")
    elif etype == "soothe.tool.search.completed":
        count = data.get("result_count", 0)
        response_time = data.get("response_time")
        parts = [f"Found {count} results"]
        if response_time:
            parts.append(f"({response_time:.1f}s)")
    elif etype == "soothe.tool.search.failed":
        error = data.get("error", "unknown error")
        parts = [f"Search failed: {str(error)[:40]}"]
    elif etype == "soothe.tool.crawl.started":
        url = data.get("url", "")
        parts = [f"Crawling: {str(url)[:50]}"]
    elif etype == "soothe.tool.crawl.completed":
        content_length = data.get("content_length", 0)
        parts = [f"Crawl complete: {content_length} bytes"]
    elif etype == "soothe.tool.crawl.failed":
        error = data.get("error", "unknown error")
        parts = [f"Crawl failed: {str(error)[:40]}"]
    # Subagent tool logging events
    elif etype in ("soothe.planner.tool_start", "soothe.scout.tool_start"):
        tool = data.get("tool", "?")
        parts = [f"Calling: {tool}"]
        # Add newline before tool events for better separation from message output
        sys.stderr.write("\n")
    elif etype in ("soothe.planner.tool_end", "soothe.scout.tool_end"):
        tool = data.get("tool", "?")
        result_preview = str(data.get("result_preview", ""))[:60]
        parts = [f"Result ({tool}): {result_preview}"]
    elif etype in ("soothe.planner.tool_error", "soothe.scout.tool_error"):
        tool = data.get("tool", "?")
        error = data.get("error", "unknown error")
        parts = [f"Error ({tool}): {str(error)[:60]}"]
    # Subagent progress events
    elif etype == "soothe.browser.step":
        step = data.get("step", "?")
        action = str(data.get("action", ""))[:40]
        url = str(data.get("url", ""))[:35]
        parts = [f"Step {step}"]
        if action:
            parts.append(f": {action}")
        if url:
            parts.append(f"@ {url}")
    elif etype == "soothe.browser.cdp":
        status = data.get("status", "")
        if status == "connected":
            parts = ["Connected to existing browser"]
        elif status == "not_found":
            parts = ["No existing browser found, launching new"]
        else:
            parts = [f"Browser CDP: {status}"]
    elif etype == "soothe.research.web_search":
        query = data.get("query", "")
        engines = data.get("engines", [])
        parts = ["Searching:", str(query)[:40]]
        if engines:
            parts.append(f"({', '.join(engines[:3])})")
    elif etype == "soothe.research.search_done":
        count = data.get("result_count", 0)
        parts = [f"Found {count} results"]
    elif etype == "soothe.research.queries_generated":
        count = data.get("count", 0)
        queries = data.get("queries", [])
        parts = [f"Generated {count} search queries"]
        if queries and len(queries) <= _MAX_INLINE_QUERIES:
            parts.append(f": {', '.join(str(q)[:30] for q in queries[:_MAX_INLINE_QUERIES])}")
    elif etype == "soothe.research.complete":
        parts = ["Research completed"]
    # Protocol events
    elif etype == "soothe.context.projected":
        parts = [f"{data.get('entries', 0)} entries, {data.get('tokens', 0)} tokens"]
    elif etype == "soothe.memory.recalled":
        parts = [f"{data.get('count', 0)} items recalled"]
    elif etype == "soothe.plan.created":
        steps = data.get("steps", [])
        parts = [f"{len(steps)} steps created"]
    elif etype == "soothe.plan.step_started":
        step_id = data.get("step_id", "?")
        description = str(data.get("description", ""))[:60]
        parts = [f"Step {step_id}: {description}"]
    elif etype == "soothe.plan.step_completed":
        step_id = data.get("step_id", "?")
        parts = [f"Step {step_id} completed"]
    elif etype == "soothe.plan.step_failed":
        step_id = data.get("step_id", "?")
        error = data.get("error", "unknown error")
        parts = [f"Step {step_id} failed: {str(error)[:60]}"]
    elif etype == "soothe.plan.reflected":
        assessment = data.get("assessment", "")
        parts = [f"Reflection: {str(assessment)[:80]}"]
    elif etype == "soothe.plan.batch_started":
        batch = data.get("batch", [])
        parts = [f"Starting batch of {len(batch)} steps"]
    elif etype == "soothe.policy.checked":
        verdict = data.get("verdict", "?")
        profile = data.get("profile")
        # In debug mode, show all policy events
        # In normal mode, suppress "allow" messages but show "deny" messages
        if verdict == "deny" or verbosity == "debug":
            parts = [verdict]
            if profile:
                parts.append(f"(profile={profile})")
        else:
            # Skip rendering "allow" events to stderr in normal mode
            return
    elif etype == "soothe.policy.denied":
        reason = data.get("reason", "denied")
        profile = data.get("profile")
        parts = [reason]
        if profile:
            parts.append(f"(profile={profile})")
    elif etype in ("soothe.thread.started", "soothe.thread.ended"):
        parts = [f"thread={data.get('thread_id', '?')}"]
    elif etype == "soothe.iteration.started":
        parts = [f"iteration {data.get('iteration', '?')}: {data.get('goal_description', '')[:60]}"]
    elif etype == "soothe.iteration.completed":
        parts = [f"iteration {data.get('iteration', '?')}: {data.get('outcome', '?')} ({data.get('duration_ms', 0)}ms)"]
    elif etype == "soothe.goal.created":
        parts = [f"{data.get('description', '')[:60]} (priority={data.get('priority', '?')})"]
    elif etype == "soothe.goal.completed":
        parts = [f"goal {data.get('goal_id', '?')} completed"]
    elif etype == "soothe.goal.failed":
        parts = [f"goal {data.get('goal_id', '?')} failed (retry {data.get('retry_count', 0)})"]
    elif etype == "soothe.goal.report":
        goal_id = data.get("goal_id", "?")
        step_count = data.get("step_count", 0)
        completed = data.get("completed", 0)
        failed = data.get("failed", 0)
        summary = data.get("summary", "")

        status = "completed" if failed == 0 else "failed"
        parts = [f"[goal] {goal_id}: {completed}/{step_count} steps {status}"]

        if failed > 0:
            parts.append(f"({failed} failed)")

        sys.stderr.write(" ".join(parts) + "\n")

        if summary:
            sys.stderr.write(f"  Summary: {summary}\n")

        sys.stderr.flush()

        return  # Prevent default printing
    elif etype == "soothe.error":
        parts = [data.get("error", "unknown")]
    else:
        summary_keys = ("query", "topic", "agent_name", "message", "skill_count", "result_count")
        for k in summary_keys:
            v = data.get(k)
            if v is not None:
                parts.append(f"{k}={v}")
                break

    detail = " ".join(parts) if parts else etype
    if prefix:
        sys.stderr.write(f"[{prefix}] [{tag}] {detail}\n")
    else:
        sys.stderr.write(f"[{tag}] {detail}\n")
    sys.stderr.flush()
