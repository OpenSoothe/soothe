# Autonomous Mode

Enable autonomous iteration for complex tasks.

## What is Autonomous Mode?

Autonomous mode allows Soothe to work independently on complex tasks that require iterative refinement. Instead of stopping after one response, Soothe will:
1. Create a plan for the goal
2. Execute the plan step-by-step
3. Reflect on results after each iteration
4. Adjust the plan if needed
5. Continue until the goal is achieved or iteration limit is reached

## When to Use Autonomous Mode

Use autonomous mode for tasks that:
- Require iterative refinement based on results
- Involve multi-phase research where findings inform next steps
- Need long-running workflows without manual intervention
- Decompose into sub-goals that emerge during execution

**Examples**:
- "Optimize the simulation parameters across the search space"
- "Research and document all API endpoints in this codebase"
- "Build a comprehensive test suite with maximum coverage"
- "Analyze and improve the performance of this application"

## How to Enable

### TUI Command

```bash
# In TUI
/autopilot Optimize the simulation parameters

# With custom iteration limit
/autopilot 15 Research and improve model performance
```

### Autopilot Command

```bash
# Dedicated autopilot command
soothe autopilot "Research quantum error correction advances"

# With iteration limit
soothe autopilot "Build a web scraper" --max-iterations 15
```

## Progress Events

During autonomous execution, you'll see progress events:

- `soothe.iteration.started` - Iteration began
- `soothe.iteration.completed` - Iteration finished
- `soothe.goal.created` - New goal created
- `soothe.goal.completed` - Goal achieved
- `soothe.goal.failed` - Goal failed

## Configuration

Set defaults in your configuration file:

```yaml
# Enable autonomous mode by default
autonomous_enabled_by_default: false

# Maximum iterations (default: 10)
autonomous_max_iterations: 10

# Maximum retries per iteration (default: 2)
autonomous_max_retries: 2
```

### Environment Variables

```bash
export SOOTHE_AUTONOMOUS_ENABLED_BY_DEFAULT=true
export SOOTHE_AUTONOMOUS_MAX_ITERATIONS=15
export SOOTHE_AUTONOMOUS_MAX_RETRIES=3
```

## How It Works

### Iteration Loop

1. **Plan Creation**: Soothe creates a plan for your goal
2. **Step Execution**: Each plan step is executed
3. **Reflection**: Results are analyzed
4. **Plan Adjustment**: Plan is updated if needed
5. **Continuation**: Loop continues until goal achieved or limit reached

### Stopping Conditions

Autonomous mode stops when:
- The goal is achieved
- Maximum iterations reached
- User cancels with `/cancel` or `Ctrl+C`
- Critical error occurs

## Examples

### Optimization Task

```bash
soothe autopilot "Optimize the database queries for better performance"
```

Soothe will:
1. Analyze current query performance
2. Identify bottlenecks
3. Optimize queries
4. Measure improvements
5. Iterate until satisfied

### Research Task

```bash
soothe autopilot "Research and document the best practices for REST API design"
```

Soothe will:
1. Research REST API best practices
2. Gather multiple sources
3. Synthesize findings
4. Create documentation
5. Refine based on gaps

### Development Task

```bash
soothe autopilot --max-iterations 25 "Build a comprehensive test suite for the authentication module"
```

Soothe will:
1. Analyze the authentication module
2. Identify test scenarios
3. Write tests
4. Run tests and check coverage
5. Add more tests iteratively

## Monitoring Progress

### TUI

In the TUI, you'll see:
- Current iteration number
- Active goals
- Plan progress
- Subagent activity
- Tool usage

### Headless Mode

With `--format jsonl`, each progress event is a JSON object:

```json
{"type": "event", "event_type": "soothe.iteration.started", "data": {"iteration": 1}}
{"type": "event", "event_type": "soothe.goal.created", "data": {"goal_id": "goal_1", "description": "..." }}
```

## Best Practices

1. **Clear Goals**: Provide specific, measurable objectives
2. **Reasonable Limits**: Start with default 10 iterations
3. **Monitor Progress**: Check in on long-running tasks
4. **Cancel if Needed**: Use `/cancel` or `Ctrl+C` to stop

## Related Guides

- [CLI Reference](cli-reference.md) - Autonomous command options
- [TUI Guide](tui-guide.md) - `/autopilot` slash command
- [Configuration Guide](configuration.md) - Autonomous mode settings