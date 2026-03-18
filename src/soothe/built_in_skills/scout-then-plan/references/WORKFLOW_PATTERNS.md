# Workflow Patterns

This document provides scenario-specific patterns for using the scout-then-plan workflow across different domains.

## Pattern 1: Software Development Projects

**Scenario**: Plan a software feature, bug fix, or architectural change

### Scout Targets (3-4 scouts)

```
task("scout", "Explore existing patterns for similar features")

task("scout", "Find dependencies and infrastructure components")

task("scout", "Identify integration points and interfaces")

task("scout", "Discover testing patterns and verification approaches")
```

### Synthesis Focus

- **Patterns**: How similar features are structured
- **Integration points**: Where to add code (files, modules)
- **Conventions**: Naming, error handling, logging
- **Testing**: How to verify the feature works

### Planner Context

Include:
- Reference implementations with file:line citations
- Integration points with code snippets
- Testing patterns to follow
- Configuration approach

### Example

**Task**: Add rate limiting to API endpoints

**Scouts**:
1. Find existing middleware patterns
2. Locate API route definitions
3. Check for rate limiting libraries
4. Review middleware test patterns

**Synthesis**:
- Middleware pattern: `app.use(middleware)` in `src/app.py:45`
- Rate limiting: `slowapi` available in requirements
- Tests: `tests/test_middleware.py` uses pytest fixtures

**Planner input**: Context about middleware registration, slowapi library, test patterns

---

## Pattern 2: Research and Analysis

**Scenario**: Plan a research project, literature review, or data analysis

### Scout Targets (3-4 scouts)

```
task("scout", "Explore existing literature and prior work")

task("scout", "Find relevant datasets and data sources")

task("scout", "Identify methodologies and frameworks")

task("scout", "Discover tools and resources needed")
```

### Synthesis Focus

- **Literature**: Prior work and key findings
- **Data**: Available sources, quality, and access
- **Methods**: Proven approaches and frameworks
- **Resources**: Tools, compute, and expertise needed

### Planner Context

Include:
- Key papers and findings with citations
- Data sources with access requirements
- Methodology options with trade-offs
- Resource requirements and constraints

### Example

**Task**: Plan a study on machine learning fairness in hiring

**Scouts**:
1. Explore fairness literature in ML
2. Find hiring datasets and bias measures
3. Identify fairness frameworks (e.g., fairlearn)
4. Discover evaluation metrics and benchmarks

**Synthesis**:
- Literature: 50+ papers on fairness in ML hiring
- Data: Synthetic datasets available; real hiring data requires IRB
- Methods: Pre-processing, in-processing, post-processing approaches
- Tools: fairlearn, AIF360 libraries available

**Planner input**: Context about fairness approaches, data constraints, evaluation framework

---

## Pattern 3: Business Process Improvement

**Scenario**: Improve a business workflow, process, or operation

### Scout Targets (3-4 scouts)

```
task("scout", "Explore current process and documentation")

task("scout", "Find pain points and inefficiencies")

task("scout", "Identify stakeholders and their requirements")

task("scout", "Discover tools and systems in use")
```

### Synthesis Focus

- **Current state**: How the process works now
- **Pain points**: Bottlenecks, delays, errors
- **Stakeholders**: Who's involved and their needs
- **Systems**: Tools, platforms, integrations

### Planner Context

Include:
- Current workflow with step-by-step breakdown
- Pain points with quantified impact
- Stakeholder requirements and priorities
- System integration points and constraints

### Example

**Task**: Improve customer onboarding process

**Scouts**:
1. Explore current onboarding workflow
2. Find pain points from customer feedback
3. Identify teams and stakeholders involved
4. Discover tools (Salesforce, Intercom, etc.)

**Synthesis**:
- Process: 12-step manual workflow with 3 handoffs
- Pain points: Step 5 causes 40% of drop-offs; data re-entry
- Stakeholders: Sales, Support, Product teams
- Systems: Salesforce, Intercom, internal tools with data silos

**Planner input**: Context about workflow bottlenecks, tool fragmentation, automation opportunities

---

## Pattern 4: Content Creation and Strategy

**Scenario**: Plan content creation, marketing campaigns, or documentation

### Scout Targets (3-4 scouts)

```
task("scout", "Explore target audience and their needs")

task("scout", "Find existing content and gaps")

task("scout", "Identify distribution channels and formats")

task("scout", "Discover success metrics and feedback")
```

### Synthesis Focus

- **Audience**: Who they are and what they need
- **Content**: What exists and what's missing
- **Channels**: Where to publish and promote
- **Metrics**: How to measure success

### Planner Context

Include:
- Audience personas with needs and preferences
- Content gaps with prioritization
- Channel strategy with format requirements
- Success metrics and tracking approach

### Example

**Task**: Create a developer documentation portal

**Scouts**:
1. Explore developer personas and use cases
2. Find existing docs and knowledge gaps
3. Identify documentation platforms and formats
4. Discover developer feedback channels

**Synthesis**:
- Audience: Backend developers, DevOps engineers, architects
- Gaps: No API reference, outdated tutorials, no best practices
- Channels: docs.website.com, GitHub, Dev.to
- Metrics: Time-to-first-api-call, support ticket reduction

**Planner input**: Context about developer needs, documentation gaps, platform requirements

---

## Pattern 5: Data Analysis and Insights

**Scenario**: Plan a data analysis, BI project, or analytics initiative

### Scout Targets (3-4 scouts)

```
task("scout", "Explore available data sources and quality")

task("scout", "Find business questions to answer")

task("scout", "Identify analysis tools and techniques")

task("scout", "Discover visualization and reporting needs")
```

### Synthesis Focus

- **Data**: Sources, quality, access, and limitations
- **Questions**: Business problems to solve
- **Methods**: Analysis approaches and tools
- **Output**: Dashboards, reports, insights format

### Planner Context

Include:
- Data sources with quality assessment
- Business questions with priority ranking
- Analysis methods with tool selection
- Visualization strategy and stakeholder needs

### Example

**Task**: Build customer churn prediction model

**Scouts**:
1. Explore customer data sources (CRM, product usage, support)
2. Find churn-related metrics and indicators
3. Identify ML tools and infrastructure
4. Discover reporting requirements for leadership

**Synthesis**:
- Data: CRM (Salesforce), usage analytics (Mixpanel), support tickets (Zendesk)
- Signals: Login frequency, feature adoption, support interactions
- Tools: Python, scikit-learn, MLflow for tracking
- Output: Weekly churn risk report for Customer Success team

**Planner input**: Context about data integration, feature engineering, model deployment, reporting

---

## Pattern 6: Project Planning

**Scenario**: Plan a multi-phase project, initiative, or program

### Scout Targets (4-5 scouts)

```
task("scout", "Explore project requirements and objectives")

task("scout", "Find resources and constraints")

task("scout", "Identify dependencies and risks")

task("scout", "Discover similar past projects and lessons")

task("scout", "Identify stakeholders and communication needs")
```

### Synthesis Focus

- **Requirements**: Goals, deliverables, success criteria
- **Resources**: Budget, team, tools, timeline
- **Dependencies**: External factors, blockers, sequencing
- **Risks**: Potential issues and mitigation strategies

### Planner Context

Include:
- Project objectives with measurable outcomes
- Resource allocation with constraints
- Dependency map with critical path
- Risk assessment with contingency plans

### Example

**Task**: Plan a cloud migration project

**Scouts**:
1. Explore current infrastructure and applications
2. Find cloud requirements and compliance needs
3. Identify migration tools and approaches
4. Discover past migration experiences and lessons
5. Identify stakeholders and training needs

**Synthesis**:
- Scope: 50 applications, 3 data centers, compliance (SOC2, GDPR)
- Resources: 6-month timeline, $2M budget, 10-person team
- Dependencies: Network connectivity, security audit, vendor contracts
- Risks: Data loss, downtime, compliance violations

**Planner input**: Context about migration phases, risk mitigation, compliance requirements, training plan

---

## General Guidelines

### Choose the Right Pattern

Match patterns to your domain:
- **Software**: Pattern 1
- **Research**: Pattern 2
- **Business processes**: Pattern 3
- **Content**: Pattern 4
- **Data analysis**: Pattern 5
- **Project management**: Pattern 6

### Customize Scout Targets

Patterns are starting points. Adjust based on:
- Task specificity and scope
- Available information
- Time constraints
- Risk tolerance

### Iterate When Needed

If initial scouts don't provide enough context:
- Launch additional targeted scouts
- Use tools to dive deeper
- Re-synthesize with new information

### Validate Plans

After planning:
- Review against synthesis findings
- Check for missed constraints
- Verify feasibility and testability
- Validate with stakeholders if needed

## Cross-Domain Principles

### Universal Scout Targets

Regardless of domain, typically explore:
1. **Current state**: What exists now
2. **Requirements**: What's needed
3. **Resources**: What's available
4. **Constraints**: What limits options

### Universal Synthesis Elements

Always synthesize:
1. **Findings**: What you discovered
2. **Patterns**: What's common or standard
3. **Gaps**: What's unknown or missing
4. **Constraints**: What must be respected

### Universal Plan Components

All plans should have:
1. **Clear steps**: Sequential actions
2. **Dependencies**: What must happen first
3. **Verification**: How to confirm success
4. **Resources**: What's needed for each step
