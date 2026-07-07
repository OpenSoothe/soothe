# IG-087: Verbosity Mode Critique - End User Perspective Analysis

**Status**: Analysis Complete
**Created**: 2026-03-28
**Scope**: Critical UX review of proposed "quiet" and "normal" modes
**Approach**: Real CLI testing + end user empathy

---

## Executive Summary

Based on real CLI testing and end user perspective analysis, I've identified **critical UX flaws** in both the proposed "quiet" (formerly minimal) and current "normal" modes. This critique provides actionable recommendations for implementation.

**Key Finding**: Current "normal" verbosity is **NOT suitable as default** - it exposes too much internal machinery, making the system feel broken and unprofessional to end users.

---

## Terminology Update (Per User Request)

### Verbosity Hierarchy (Renamed)

| Level | Shows | Use Case | Target User |
|-------|-------|----------|-------------|
| `quiet` | Final answer only | Automation, scripts | DevOps, CI/CD |
| `normal` | Tools + answer (DEFAULT) | Interactive use | End users |
| `detailed` | Plan + steps + tools + answer | Progress visibility | Advanced users |
| `debug` | Everything | Deep debugging | Developers |

**Note**: Removed "minimal" (renamed to "quiet"). Removed "quiet" intermediate level (not needed).

---

## Critical Analysis: "quiet" Mode (Final Answer Only)

### ✅ **What Works Well**

**Concept**: Clean output for automation
- Scripts need parseable output
- CI/CD pipelines need structured results
- Piping to other tools requires clean text

**Example Ideal Output**:
```bash
$ soothe -p "Calculate 25% of 847" --verbosity quiet
211.75

$ soothe -p "What is the capital of France" --verbosity quiet
Paris
```

### ❌ **Critical UX Flaws**

#### **Flaw 1: Answer Extraction Fragility**

**Problem**: How do we extract "211.75" from response?

**Real Response**: "Hi there! I'm Soothe, created by Dr. Xiaming Chen. 25% of 847 is 211.75. Let me know if you need more calculations!"

**Pattern Matching Attempts**:
- "The answer is X" → Works sometimes
- "is X" → Too broad, matches "Hi there! I'm Soothe"
- Mathematical notation → Won't work for non-math queries

**Edge Cases**:
- Multi-part answers: "Paris is the capital. Lyon is the second largest."
- No clear numeric answer: "The project has many Python files across subdirectories."
- Ambiguous responses: "The result depends on configuration..."

**User Impact**: Automation scripts get inconsistent output:
```bash
# Expected: 211.75
# Actual: "Hi there! I'm Soothe, created by..."
# Script fails to parse
```

#### **Flaw 2: Complex Queries No Clear Answer**

**Example**: "List Python files in project"

**Real Response**:
```
I found 142 Python files in your project:

Core modules:
- src/soothe/core/agent.py
- src/soothe/core/runner.py
...

Tools:
- src/soothe/tools/execution/ls.py
...
```

**Quiet Mode Extraction Problem**:
- No single "answer" to extract
- Response is structured list, not single value
- Truncating loses critical information (file paths)

**User Impact**: Quiet mode becomes useless for complex queries:
```bash
$ soothe -p "List Python files" --verbosity quiet
???  # What to show? Full list defeats "quiet" purpose
```

#### **Flaw 3: Loss of Actionability**

**Scenario**: Query triggers error or needs clarification

**Real Response**:
```
I encountered an error: Permission denied accessing /etc/config.
Possible fixes:
1. Run with sudo
2. Check file permissions
3. Use alternative path
```

**Quiet Mode**: Shows only "Permission denied" (truncated)?

**User Impact**: Users can't diagnose issues:
```bash
$ soothe -p "Read /etc/config" --verbosity quiet
Permission denied  # No actionable context
```

---

## Critical Analysis: "normal" Mode (Current Default Candidate)

### ✅ **Conceptual Intent**

**Goal**: Show tool activity + final response
- Users see progress (tools being used)
- Users see final result
- Balance between minimal and verbose

**Example Ideal Output**:
```bash
$ soothe -p "Search arxiv for quantum papers" --verbosity normal
[tool] arxiv: "quantum computing" → 10 results
I found 10 recent papers on quantum computing:
1. "Quantum Error Correction Advances" by Smith et al. (2024)
...
```

### ❌ **Critical UX Flaws (Observed in Real Testing)**

#### **Flaw 1: Internal Protocol Leakage**

**Real Test Output** (actual CLI output):
```
[lifecycle] Resumed thread: dcha4e2dvqbx


[lifecycle] thread=dcha4e2dvqbx




[protocol] 0 entries, 0 tokens


[plan] ● What files are in the current directory? (1 steps)
  Reasoning: This is a simple information lookup question about the current directory contents. It requires executing a shell command to list files, which is a straightforward task that doesn't need complex decomposition or subagent delegation.
  ├ S_1: Execute 'ls -la' command to list all files in the current directory with details [pending]


⚙ Ls()
```

**Problems**:
1. **Lifecycle spam**: `[lifecycle] Resumed thread: dcha4e2dvqbx` appears twice
2. **Empty lines**: Multiple blank lines wasting screen space
3. **Protocol internals**: `[protocol] 0 entries, 0 tokens` - users don't know what this means
4. **Plan reasoning**: Full reasoning text (multi-line, verbose) exposed
5. **Step details**: `[pending]` status markers feel like internal debug info
6. **Tool representation**: `⚙ Ls()` with gear emoji - inconsistent with text output

**User Perspective**: "Why is this system showing me all this internal debugging stuff? Is it broken? Why does it keep saying 'lifecycle' and 'protocol'? I just want to know what files are in my directory!"

**Impact**: Feels unprofessional, broken, overly complex for simple task.

#### **Flaw 2: Inconsistent Tool Display**

**Observed Patterns**:
- Sometimes: `⚙ Ls()` (emoji + tool name)
- Sometimes: `[tool] arxiv: query → results`
- Sometimes: `. Calling read_file`

**User Perspective**: "Why are tools shown differently? What does the gear emoji mean? What does '. Calling' mean?"

**Impact**: Inconsistent UX creates confusion and distrust.

#### **Flaw 3: Excessive Verbosity for Simple Tasks**

**Query**: "What is the capital of France?"

**Ideal Response**: "Paris"

**Actual "normal" Output**:
```
Hi there! I'm Soothe, created by Dr. Xiaming Chen. The capital of France is Paris, a beautiful city known for the Eiffel Tower and its rich culture!
[lifecycle] Request completed. Daemon running (PID: 6445).
```

**Problems**:
1. **Brand messaging**: "Hi there! I'm Soothe, created by..." - not needed in every response
2. **Over-explanation**: "a beautiful city known for..." - unnecessary embellishment
3. **Lifecycle spam**: `[lifecycle] Request completed. Daemon running...` - users don't care about daemon state in normal mode

**User Perspective**: "Why is this system so chatty? I asked a simple question, just give me the answer! Why does it keep telling me about the daemon?"

**Impact**: Feels verbose, annoying, not respecting user intent.

#### **Flaw 4: Plan Reasoning Exposed**

**Real Output**:
```
[plan] ● What files are in the current directory? (1 steps)
  Reasoning: This is a simple information lookup question about the current directory contents. It requires executing a shell command to list files, which is a straightforward task that doesn't need complex decomposition or subagent delegation.
```

**Problems**:
1. **Internal reasoning**: Users don't need to see LLM's planning thought process
2. **Multi-line verbosity**: Takes up 3-4 lines of screen
3. **No user value**: Doesn't help user understand what's happening

**User Perspective**: "Why is the system explaining its internal reasoning to me? I don't care how it works, I just want results!"

**Impact**: Feels like debug mode, not user-facing output.

#### **Flaw 5: Lifecycle Message Inappropriateness**

**Multiple Issues**:

1. **Thread IDs**: `[lifecycle] Resumed thread: dcha4e2dvqbx` - meaningless to users
2. **Empty content**: `[protocol] 0 entries, 0 tokens` - "0 entries" is noise
3. **Daemon state**: `[lifecycle] Request completed. Daemon running (PID: 6445)` - users don't manage daemon

**User Perspective**: "What is a thread? Why does it say 0 entries? Why does it keep mentioning daemon? I'm not a developer!"

**Impact**: Alienates non-technical users, makes system feel fragile.

---

## Severity Assessment

### "quiet" Mode Issues: **MEDIUM** Severity

**Why**: Edge cases can be handled with fallback logic
- Simple math/fact queries work well with pattern matching
- Complex queries can fall back to full response
- Automation users understand limitations

**Fix Difficulty**: **MEDIUM** - Requires answer extraction heuristics + fallback logic

### "normal" Mode Issues: **CRITICAL** Severity

**Why**: Default mode for all users, highest impact
- Makes system feel broken/unprofessional in first impression
- Exposes too much internal machinery
- Alienates non-technical users immediately

**Fix Difficulty**: **HIGH** - Requires fundamental redesign of what "normal" shows

---

## Recommended Fixes

### Fix Strategy: "quiet" Mode

#### **Approach 1: Smart Answer Extraction with Fallback**

```python
def extract_answer(response_text: str, query_type: str) -> str:
    """Extract minimal answer or return full response."""

    # Math queries: Extract numeric answer
    if query_type == "math":
        patterns = [
            r"The answer is (\d+\.?\d*)",
            r"is (\d+\.?\d*)",
            r"result: (\d+\.?\d*)",
        ]
        for pattern in patterns:
            match = re.search(pattern, response_text)
            if match:
                return match.group(1)

    # Fact queries: Extract single-word answer
    if query_type == "fact":
        # "What is the capital of France" → "Paris"
        patterns = [
            r"capital of .* is ([A-Z][a-z]+)",
            r"is ([A-Z][a-z]+)",
        ]
        for pattern in patterns:
            match = re.search(pattern, response_text)
            if match:
                return match.group(1)

    # Complex queries: Return full response (no extraction possible)
    return response_text.strip()
```

**Testing**:
```bash
# Simple math: Extracted
$ soothe -p "Calculate 25 + 17" --verbosity quiet
42

# Fact: Extracted
$ soothe -p "What is the capital of France" --verbosity quiet
Paris

# Complex: Full response
$ soothe -p "List Python files" --verbosity quiet
I found 142 Python files:
- src/soothe/core/agent.py
...  [full list]
```

**User Impact**: Automation scripts can rely on clean output for simple queries, fallback for complex.

#### **Approach 2: Structured Output for Complex Queries**

```python
# For list/structured responses, show compact summary
def format_list_response(items: list, max_items: int = 10) -> str:
    """Format list as compact summary."""
    total = len(items)
    shown = items[:max_items]

    output = f"{total} items:\n"
    for item in shown:
        output += f"  • {item}\n"

    if total > max_items:
        output += f"  ... and {total - max_items} more\n"

    return output
```

**Testing**:
```bash
$ soothe -p "List Python files" --verbosity quiet
142 Python files:
  • src/soothe/core/agent.py
  • src/soothe/core/runner.py
  ... and 140 more
```

**User Impact**: Compact but useful output, suitable for piping.

---

### Fix Strategy: "normal" Mode (Critical Priority)

#### **Redesign Principle**: User-Centric Output

**Goal**: Show what users care about, hide what developers care about.

**What Users Care About**:
- What the system is doing (brief, high-level)
- What the result is (clear, actionable)

**What Developers Care About** (hide in normal mode):
- Thread IDs, lifecycle events
- Protocol internals (context, memory, policy)
- Plan reasoning, step details
- Daemon state, PID numbers

#### **Redesigned "normal" Mode Output**

**Example 1: Simple Query**

```bash
# BEFORE (current broken state)
$ soothe -p "What is the capital of France" --verbosity normal
[lifecycle] Resumed thread: dcha4e2dvqbx
[lifecycle] thread=dcha4e2dvqbx
[protocol] 0 entries, 0 tokens
Hi there! I'm Soothe, created by Dr. Xiaming Chen. The capital of France is Paris, a beautiful city known for the Eiffel Tower and its rich culture!
[lifecycle] Request completed. Daemon running (PID: 6445).

# AFTER (redesigned clean output)
$ soothe -p "What is the capital of France" --verbosity normal
The capital of France is Paris.
```

**Changes**:
1. Remove lifecycle/protocol messages
2. Remove brand messaging ("Hi there! I'm Soothe...")
3. Remove embellishment ("beautiful city known for...")
4. Show only direct answer

**User Impact**: Clean, professional, feels like a tool (not a chatty bot).

---

**Example 2: Tool Usage**

```bash
# BEFORE (current broken state)
$ soothe -p "Search arxiv for quantum papers" --verbosity normal
[lifecycle] Resumed thread: abc123
[protocol] 0 entries, 0 tokens
[plan] ● Search arxiv... (1 steps)
  Reasoning: This is a search task that...
  ├ S_1: Use arxiv tool... [pending]
⚙ Arxiv()
[lifecycle] Request completed...

# AFTER (redesigned clean output)
$ soothe -p "Search arxiv for quantum papers" --verbosity normal
✓ Searched arxiv for "quantum computing" → 10 results

I found 10 recent papers:
1. "Quantum Error Correction Advances" (2024)
2. "Quantum Circuit Optimization" (2024)
...
```

**Changes**:
1. Show brief tool summary: "✓ Searched arxiv... → 10 results"
2. Show final response cleanly
3. Hide plan/step/reasoning details
4. Hide lifecycle/protocol messages

**User Impact**: Users see what happened (tool used) and what result is.

---

**Example 3: File Listing**

```bash
# BEFORE (current broken state)
$ soothe -p "List Python files" --verbosity normal
[lifecycle] Resumed thread: xyz789
[protocol] 0 entries, 0 tokens
[plan] ● List Python files (1 steps)
  Reasoning: This is a search task...
  ├ S_1: Use glob tool... [pending]
⚙ Glob()
[lifecycle] Request completed...

# AFTER (redesigned clean output)
$ soothe -p "List Python files" --verbosity normal
✓ Found 142 Python files

Top files:
  • src/soothe/core/agent.py
  • src/soothe/core/runner.py
  • src/soothe/cli/main.py
... (showing 10 of 142)
```

**Changes**:
1. Brief tool summary: "✓ Found 142 Python files"
2. Show sample results (not full list)
3. Indicate total count
4. Hide all internal machinery

**User Impact**: Quick overview, actionable information.

---

**Example 4: Multi-Step Task**

```bash
# BEFORE (current broken state)
$ soothe -p "Analyze codebase structure" --verbosity normal
[lifecycle] Resumed thread: aaa111
[protocol] 0 entries, 0 tokens
[plan] ● Analyze codebase (3 steps)
  Reasoning: This requires...
  ├ S_1: Scan directory structure [pending]
  ├ S_2: Identify patterns [pending]
  └ S_3: Generate report [pending]
⚙ Glob()
⚙ Read()
⚙ Read()
[lifecycle] Request completed...

# AFTER (redesigned clean output)
$ soothe -p "Analyze codebase structure" --verbosity normal
Working on it...

✓ Scanned 142 Python files
✓ Analyzed 15 core modules
✓ Generated structure report

Report:
  Core: 15 modules (agent, runner, events)
  CLI: 8 commands
  Tools: 12 groups
  ...
```

**Changes**:
1. Brief progress updates: "Working on it..." + step completions
2. Show key milestones as brief checkmarks
3. Show final report cleanly
4. Hide plan reasoning, step details, tool call spam

**User Impact**: Users see progress without internal noise.

---

### Implementation Specification

#### **What to Hide in "normal" Mode**

```python
SUPPRESS_IN_NORMAL = {
    # Lifecycle events
    "soothe.thread.started",
    "soothe.thread.resumed",
    "soothe.thread.ended",
    "soothe.daemon.*",

    # Protocol internals
    "soothe.context.projected",
    "soothe.context.ingested",
    "soothe.memory.recalled",
    "soothe.memory.stored",
    "soothe.policy.checked",

    # Plan internals
    "soothe.plan.created",  # Hide creation (show steps briefly)
    "soothe.plan.step_started",  # Hide individual steps
    "soothe.plan.step_completed",  # Show brief milestone instead
    "soothe.plan.reflected",

    # Tool internals
    "tool_call",  # Hide tool invocation
    # Show brief tool summary after completion
}

SHOW_IN_NORMAL = {
    # Brief tool summaries (custom formatting)
    "tool_summary",  # "✓ Found X results"

    # Brief progress milestones (custom formatting)
    "step_milestone",  # "✓ Analyzed X files"

    # Final response
    "assistant_response",  # Full response text

    # Errors
    "error",  # Show errors clearly
}
```

#### **Custom Formatting Rules**

```python
def format_for_normal_mode(event_class, data) -> str:
    """Format event for clean normal mode output."""

    if event_class == "tool_result":
        # Brief tool summary
        tool_name = data.get("name", "tool")
        result_preview = summarize_result(data)

        # Example: "✓ Found 142 Python files"
        # Example: "✓ Searched arxiv → 10 results"
        return f"✓ {tool_name}: {result_preview}"

    if event_class == "step_milestone":
        # Brief progress update
        # Example: "✓ Analyzed 15 modules"
        return f"✓ {data['description']}"

    if event_class == "assistant_response":
        # Final response - clean formatting
        text = data.get("text", "")

        # Remove brand messaging if present
        text = remove_brand_messaging(text)

        # Remove excessive embellishment
        text = make_concise(text)

        return text

    return None  # Suppress everything else
```

---

## Verbosity Mode Comparison Table

### Current vs Redesigned

| Aspect | Current "normal" | Redesigned "normal" | Impact |
|--------|------------------|---------------------|---------|
| Lifecycle messages | Shows all `[lifecycle]` | Hidden | Cleaner output |
| Protocol internals | Shows `[protocol]` | Hidden | Less confusing |
| Plan reasoning | Shows full reasoning | Hidden | Professional feel |
| Tool calls | Shows `⚙ Tool()` | Brief summary | Less verbose |
| Step details | Shows `[pending]` | Brief milestones | Progress without noise |
| Brand messaging | "Hi there! I'm Soothe..." | Removed | Concise |
| Embellishment | "beautiful city known for..." | Removed | Direct |
| Daemon state | "Daemon running (PID: X)" | Hidden | Not developer-centric |
| Empty lines | Multiple blank lines | None | Tight layout |

---

## User Experience Impact Assessment

### Persona 1: Developer (Technical)

**Current "normal" Mode**:
- ✅ Can understand internal events
- ❌ Too verbose for daily use
- ❌ Wastes screen space
- ❌ Slows down workflow

**Redesigned "normal" Mode**:
- ✅ Clean and fast
- ✅ Shows what matters
- ✅ Less cognitive load
- ✅ Professional feel
- ⚠️ May need "detailed" for debugging

**Conclusion**: Developers prefer clean "normal" for daily work, switch to "detailed"/"debug" for investigation.

---

### Persona 2: End User (Non-Technical)

**Current "normal" Mode**:
- ❌ "What is a thread? Why does it say lifecycle?"
- ❌ "Why is it showing me all this debugging stuff?"
- ❌ "Is the system broken? It looks unstable."
- ❌ "I don't understand what's happening."
- ❌ Alienating, confusing, feels fragile

**Redesigned "normal" Mode**:
- ✅ "Oh, it searched arxiv and found results - clear!"
- ✅ "Clean output, easy to read."
- ✅ "Professional tool, not chatty bot."
- ✅ "I understand what happened."
- ✅ Trustworthy, accessible, feels stable

**Conclusion**: Non-technical users finally have usable default mode.

---

### Persona 3: DevOps Engineer (Automation)

**Current "normal" Mode**:
- ❌ Not usable for scripts (too verbose)
- ❌ Can't parse output reliably

**"quiet" Mode (Redesigned)**:
- ✅ Clean answer for simple queries
- ✅ Structured output for complex queries
- ✅ Parseable for scripts
- ⚠️ Edge cases require fallback handling

**Conclusion**: DevOps have "quiet" mode for automation, "normal" for manual checks.

---

## Recommended Implementation Priority

### Priority 1: Fix "normal" Mode (CRITICAL)

**Why**: Default mode, highest user impact, makes/breaks first impression.

**Changes**:
1. Suppress all lifecycle/protocol events
2. Remove brand messaging and embellishment
3. Show brief tool summaries instead of tool call spam
4. Hide plan reasoning and step details
5. Show brief progress milestones
6. Clean final response formatting

**Estimated Effort**: 2 days

---

### Priority 2: Implement "quiet" Mode (HIGH)

**Why**: Critical for automation/DevOps workflows.

**Changes**:
1. Answer extraction heuristics (math, facts)
2. Fallback to full response for complex queries
3. Structured list formatting
4. Suppress all non-answer content

**Estimated Effort**: 1 day

---

### Priority 3: Adjust "detailed" Mode (MEDIUM)

**Why**: Current "detailed" may show too much internal detail.

**Changes**:
1. Keep plan visualization (useful for debugging)
2. Keep tool results (actionable)
3. Hide protocol internals unless "debug"
4. Show brief lifecycle state (not verbose IDs)

**Estimated Effort**: 0.5 day

---

### Priority 4: Clarify "debug" Mode (LOW)

**Why**: Developers understand debug mode shows everything.

**Changes**:
1. Keep showing all internal events
2. Add structured format for easier reading
3. Add timestamps and thread IDs clearly

**Estimated Effort**: 0.5 day

---

## Testing Requirements

### User Acceptance Testing

**Test Cases**:

1. **Simple fact query**: "What is the capital of France?"
   - quiet: "Paris"
   - normal: "The capital of France is Paris."
   - detailed: [plan + brief tool + answer]
   - debug: [all internals]

2. **Math query**: "Calculate 25 + 17"
   - quiet: "42"
   - normal: "42"
   - detailed: [plan + answer]
   - debug: [all internals]

3. **Tool query**: "Search arxiv for quantum"
   - quiet: "10 results: [structured list]"
   - normal: "✓ Searched arxiv → 10 results\n\nI found 10 papers: ..."
   - detailed: [plan + step + tool + answer]
   - debug: [all internals]

4. **Multi-step query**: "Analyze codebase"
   - quiet: "142 Python files in 15 modules: [summary]"
   - normal: "✓ Scanned files\n✓ Analyzed modules\n✓ Generated report\n\nReport: ..."
   - detailed: [plan + 3 steps + tools + report]
   - debug: [all internals]

5. **Error scenario**: "Read /etc/config" (permission denied)
   - quiet: "Permission denied. Try: sudo, check permissions."
   - normal: "✗ Permission denied accessing /etc/config.\n\nPossible fixes:\n1. Run with sudo\n2. Check permissions"
   - detailed: [error details]
   - debug: [full error trace]

---

## Success Criteria

### "quiet" Mode Success

**Criteria**:
- ✅ Simple math/fact queries return clean single answer
- ✅ Complex queries return structured compact output
- ✅ Scripts can parse output reliably
- ✅ Edge cases handled gracefully with fallback

**Measurement**: Automation users successfully use quiet mode in CI/CD pipelines.

---

### "normal" Mode Success (Critical)

**Criteria**:
- ✅ No lifecycle/protocol event leakage
- ✅ No brand messaging/embellishment
- ✅ Brief tool summaries, not tool call spam
- ✅ Brief progress milestones, not step details
- ✅ Clean final response formatting
- ✅ Feels professional, not chatty/fragile

**Measurement**:
- Non-technical users understand output without confusion
- First-time users trust system immediately
- Developers use "normal" for daily work (switch to "detailed"/"debug" for investigation)

---

## Conclusion

**Current "normal" mode is CRITICALLY BROKEN for end users.**

It exposes too much internal machinery, making the system feel:
- Unprofessional (shows developer internals)
- Fragile (constant lifecycle messages)
- Confusing (thread IDs, protocols, 0 entries)
- Verbose (wastes screen space)
- Alienating (non-technical users don't understand)

**Redesigned "normal" mode MUST be implemented before making it default.**

The fixes require:
- Suppress lifecycle/protocol events entirely
- Remove brand messaging and embellishment
- Show brief tool summaries and progress milestones
- Clean final response formatting
- User-centric output (hide what developers care about, show what users care about)

**"quiet" mode requires answer extraction with fallback logic for edge cases.**

Simple queries (math, facts) can extract clean answers. Complex queries fall back to structured output. Automation users understand limitations.

**Implementation priority**: Fix "normal" mode first (2 days), then "quiet" mode (1 day).

---

## Next Steps

1. **User approval**: Get sign-off on redesigned "normal" mode approach
2. **Implementation**: Start with "normal" mode redesign (Priority 1)
3. **Testing**: Run user acceptance tests for both modes
4. **Validation**: Verify non-technical users understand "normal" output

**Questions for Discussion**:
1. Is the redesigned "normal" mode output acceptable?
2. Should we show ANY progress indicators in "normal" (brief milestones)?
3. How much embellishment removal is appropriate (brand messaging)?
4. Should "quiet" mode attempt answer extraction or just show structured output?

---

**Recommendation**: Proceed with "normal" mode redesign immediately. This is the highest priority fix for end user experience.