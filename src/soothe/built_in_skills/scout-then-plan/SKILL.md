---
name: scout-then-plan
description: >
  General-purpose planning workflow combining parallel exploration with synthesized plan generation.
  Use for any complex task requiring upfront planning: software development, research, business workflows,
  content creation, data analysis, project management, or any domain. Use when user requests "scout then plan",
  "explore and plan", or mentions "parallel exploration" with planning. Ideal for tasks requiring
  broad context gathering before committing to a plan.
metadata:
  author: soothe
  version: "1.0"
---

# Scout-Then-Plan Workflow

## Overview

This skill guides you through a general-purpose 3-phase planning workflow that combines parallel exploration with systematic synthesis and structured plan generation. Applicable across all domains, workspaces, and task types.

**When to use**:
- Planning complex projects or initiatives
- Analyzing unfamiliar domains or systems
- Tasks requiring multiple exploration angles
- Research, analysis, or investigation work
- Business workflows and processes
- Content creation and strategy
- Data analysis and insights generation
- User explicitly requests "scout then plan" or "explore and plan"

**Workflow phases**:
1. **Parallel Scouting**: Launch multiple scout subagents to explore different aspects
2. **Analysis & Synthesis**: Process findings, identify patterns, and synthesize context
3. **Plan Generation**: Create structured plan using planner subagent with synthesized context

## Phase 1: Parallel Scouting

### Goal
Gather broad context by launching multiple scout subagents in parallel, each targeting a specific aspect of the task.

### How to Execute

Use the `task` tool to invoke the scout subagent multiple times with focused targets:

```
# Example: Planning a research project
task("scout", "Explore existing literature on the topic")
task("scout", "Find relevant datasets and methodologies")
task("scout", "Identify key researchers and recent work")

# Example: Planning a software feature
task("scout", "Explore existing patterns in the codebase")
task("scout", "Find dependencies and infrastructure")
task("scout", "Identify integration points and constraints")

# Example: Planning a business process improvement
task("scout", "Explore current workflow and pain points")
task("scout", "Find tools and systems in use")
task("scout", "Identify stakeholder requirements")

# Example: Planning content creation
task("scout", "Explore target audience and their needs")
task("scout", "Find existing content and gaps")
task("scout", "Identify distribution channels")
```

### Scout Target Selection

Choose 2-4 targets that cover different aspects based on your domain:

**For software development**:
- Existing patterns and implementations
- Dependencies and infrastructure
- Testing and verification approaches
- Integration points and interfaces

**For research projects**:
- Literature and prior work
- Data sources and availability
- Methodologies and frameworks
- Tools and resources needed

**For business workflows**:
- Current processes and stakeholders
- Systems and tools in use
- Pain points and inefficiencies
- Compliance and regulatory requirements

**For content creation**:
- Target audience and their needs
- Existing content and gaps
- Distribution channels and formats
- Success metrics and feedback

**For project management**:
- Stakeholders and their requirements
- Resources and constraints
- Dependencies and risks
- Timeline and milestones

**For data analysis**:
- Data sources and quality
- Analysis tools and techniques
- Business questions to answer
- Visualization and reporting needs

### Expected Outputs

Each scout returns structured findings with:
- **Target**: What was explored
- **Findings**: Numbered list with source citations
- **Confidence**: low/medium/high
- **Gaps**: Remaining unknowns

Collect all scout outputs in your working memory (conversation messages).

## Phase 2: Analysis & Synthesis

### Goal
Process scout findings, dive deeper with tools, identify patterns, and synthesize into structured context for planning.

### How to Execute

#### Step 1: Process Scout Findings

Review each scout output:
- Note high-confidence findings
- Identify overlapping patterns across scouts
- Highlight critical gaps

#### Step 2: Dive Deeper

Use appropriate tools to investigate key items identified by scouts:

```
# For any file-based exploration
read_file(path="path/to/document")
grep(pattern="keyword", output_mode="content")
glob(pattern="**/*.ext")

# The scout subagent can explore any file type:
# - Code files (.py, .js, .go, etc.)
# - Documents (.md, .txt, .pdf, .doc)
# - Data files (.csv, .json, .yaml)
# - Configuration files (.yml, .toml, .ini)
```

#### Step 3: Synthesize Findings

Create a structured synthesis with these sections:

**Findings Summary**:
- What you discovered (with source citations)
- Key patterns or themes identified
- Critical constraints or dependencies

**Patterns**:
- Common approaches or themes observed
- Conventions and standards followed
- Best practices or proven methods

**Gaps**:
- What remains unknown
- Areas needing clarification
- Risks or uncertainties

**Context for Planning**:
- Summary in 3-5 sentences
- Most relevant information and patterns
- Constraints to respect

#### Step 4: Reflect

Ask yourself:
- Did the scouts cover all necessary aspects?
- Are there contradictions or ambiguities?
- What additional context would help the planner?

If critical gaps exist, consider launching additional scouts.

### Working Memory

Store intermediate results in conversation messages:
- Scout outputs appear as tool results
- Synthesis notes in your reasoning
- File contents you've read
- No explicit state management needed

## Phase 3: Plan Generation

### Goal
Create a structured plan using the planner subagent, enriched with synthesized context.

### How to Execute

#### Step 1: Invoke Planner Subagent

Use the `task` tool with synthesized context:

```
task("planner", "Create implementation plan for [goal].\n\nContext:\n[Your synthesis summary]\n\nKey Findings:\n1. [Finding with citation]\n2. [Finding with citation]\n\nPatterns:\n- [Pattern description]\n\nConstraints:\n- [Constraint]\n\nPlease create a structured plan respecting these patterns and constraints.")
```

#### Step 2: Review Planner Output

The planner returns structured steps with:
- **Step N: Title**
- **Description**: What to do
- **Rationale**: Why this step matters
- **Dependencies**: Prior steps required
- **Verification**: How to confirm completion
- **Effort**: small/medium/large

#### Step 3: Refine Plan

Validate the plan against your synthesis:
- Does it address the original goal?
- Does it respect identified patterns?
- Are dependencies properly ordered?
- Is verification realistic?

If gaps exist, iterate:
- Launch additional scouts for unclear areas
- Re-synthesize with new findings
- Re-invoke planner with refined context

## Example: Complete Workflow

**Task**: Plan a customer onboarding process improvement

### Phase 1: Parallel Scouting

```
task("scout", "Explore current onboarding workflow and documentation")

task("scout", "Find tools and systems used in the onboarding process")

task("scout", "Identify pain points reported by customers and staff")
```

**Scout outputs**:
- Scout 1: 12-step manual process with 3 handoffs, documented in Notion
- Scout 2: Uses Salesforce, Intercom, and internal tools; data silos exist
- Scout 3: Customers report confusion at step 5; staff cite data entry duplication

### Phase 2: Analysis & Synthesis

```
read_file(path="docs/onboarding-process.md")
grep(pattern="handoff", output_mode="content")
```

**Synthesis**:
- **Findings**: Manual 12-step process with redundant data entry and multiple handoffs. Integration gaps between Salesforce and Intercom cause delays.
- **Patterns**: Paper-based approvals still used; customer communication is ad-hoc
- **Gaps**: Unknown why customers struggle specifically at step 5
- **Context**: "Current onboarding is a 12-step manual process with 3 handoffs between teams. Customers report confusion at step 5. Tools are fragmented (Salesforce, Intercom, internal tools) with data silos causing duplication. Need to understand the specific issue at step 5 and explore automation opportunities."

### Phase 3: Plan Generation

```
task("planner", "Create implementation plan for improving customer onboarding.\n\nContext:\nCurrent onboarding is a 12-step manual process with 3 handoffs between teams. Customers report confusion at step 5. Tools are fragmented (Salesforce, Intercom, internal tools) with data silos causing duplication.\n\nKey Findings:\n1. 12-step manual process documented in Notion (scout output)\n2. Uses Salesforce, Intercom, internal tools with data silos (scout output)\n3. Customer confusion at step 5; staff cite data duplication (scout output)\n\nPatterns:\n- Paper-based approvals still used\n- Ad-hoc customer communication\n\nConstraints:\n- Must maintain compliance with data regulations\n- Cannot replace Salesforce (company standard)\n\nPlease create a structured plan for improving the onboarding process.")
```

**Planner output**: Structured plan with steps for:
1. Investigate step 5 confusion (user research)
2. Map data flow and identify integration points
3. Design automated workflow with Salesforce-Intercom sync
4. Create self-service customer portal
5. Pilot with small customer segment
6. Measure and iterate

## Best Practices

### Scouting
- Launch 2-4 scouts (balance breadth vs. depth)
- Keep targets specific and non-overlapping
- Use scouts for exploration, not execution
- Adapt targets to your specific domain

### Synthesis
- Citations are critical (source references)
- Identify both patterns and anti-patterns
- Highlight gaps honestly
- Focus on actionable insights

### Planning
- Provide rich context to planner
- Include concrete references
- Respect existing patterns and constraints
- Define clear success criteria

### Iteration
- Don't hesitate to launch additional scouts if gaps emerge
- Re-synthesize as new information arrives
- Refine plans based on reflection
- Adapt the workflow to your specific needs

## Error Recovery

**Scout returns insufficient findings**:
- Re-launch with refined target
- Try different search terms or angles
- Manually explore with available tools

**Planner produces unrealistic plan**:
- Provide more context about constraints
- Explicitly mention patterns to follow
- Request verification strategies
- Consider resource limitations

**Contradictory findings**:
- Launch targeted scouts to resolve
- Consult additional sources or stakeholders
- Ask user for clarification

## Output Templates

For structured outputs, see:
- [Synthesis Template](references/OUTPUT_TEMPLATES.md#synthesis-template)
- [Plan Template](references/OUTPUT_TEMPLATES.md#plan-template)
- [Workflow Patterns](references/WORKFLOW_PATTERNS.md)

## Summary

The scout-then-plan workflow transforms planning from a single-step activity into a structured process:
1. **Scout broadly** to gather comprehensive context from multiple angles
2. **Synthesize thoughtfully** to identify patterns and gaps
3. **Plan systematically** with enriched context

This approach produces higher-quality plans by ensuring broad understanding before committing to a course of action. It works across all domains and task types, from software development to research, business processes to content creation.
