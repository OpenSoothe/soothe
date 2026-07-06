# Quick-Start Guide

Get up and running with Soothe in minutes. This guide walks you through your first session and common workflows.

---

## Prerequisites

Before starting, ensure you have:

- ✅ Soothe installed (`pip install -U 'soothe[all]' soothe-cli soothe-daemon`)
- ✅ API key set (`export OPENAI_API_KEY=sk-your-key-here`)
- ✅ Daemon started (`soothed start` — auto-creates `~/.soothe/`)

Need help? See the [Installation Guide](Installation.md).

---

## Your First Session

### Interactive TUI Mode (Recommended)

Launch the interactive terminal UI:

```bash
soothe
```

This opens the Soothe TUI with:
- Real-time progress visualization
- Task planning and decomposition
- Subagent activity tracking
- Thread history

**Example interaction:**

```
┌─ Soothe TUI ─────────────────────────────────────────┐
│                                                      │
│ > List all Python files and count lines of code     │
│                                                      │
│ [Planning] Analyzing workspace...                    │
│ [Explore] Searching for *.py files...              │
│ [Execute] Found 42 files, counting lines...         │
│                                                      │
│ ✓ Found 42 Python files with 8,547 total lines     │
│   - Largest: src/main.py (1,234 lines)              │
│   - Smallest: __init__.py files (avg 15 lines)      │
│                                                      │
│ > _                                                 │
└──────────────────────────────────────────────────────┘
```

### One-Shot Prompt Mode

Run a single query and exit:

```bash
soothe -p "What is the architecture of this project?"
```

Perfect for:
- Quick questions
- Scripts and automation
- CI/CD pipelines

---

## Basic Usage Patterns

### 1. Code Exploration

Understand a codebase:

```bash
soothe -p "Analyze the project structure and explain the main components"
```

**What happens:**
1. Soothe explores the directory structure
2. Identifies key files and modules
3. Reads documentation and code
4. Synthesizes an architectural overview

**Example output:**
```
This is a Python web application with three main layers:

1. API Layer (src/api/)
   - FastAPI endpoints for REST API
   - Request validation with Pydantic
   - Authentication middleware

2. Business Logic (src/services/)
   - User management
   - Data processing
   - External integrations

3. Data Layer (src/db/)
   - PostgreSQL database
   - SQLAlchemy ORM models
   - Migration scripts

Key dependencies: FastAPI, SQLAlchemy, Redis, PostgreSQL
```

### 2. File Operations

Manipulate files safely:

```bash
soothe -p "Create a README.md with installation instructions based on setup.py"
```

**What happens:**
1. Soothe reads `setup.py` to understand dependencies
2. Identifies entry points and requirements
3. Generates comprehensive README.md
4. Shows a preview before writing (requires confirmation)

### 3. Research Tasks

Conduct multi-source research:

```bash
soothe -p "Research the latest advances in transformer architectures and summarize key papers from 2024"
```

**What happens:**
1. Searches academic databases (arXiv, DeepXiv)
2. Retrieves and analyzes papers
3. Synthesizes findings
4. Provides citations and summaries

### 4. Code Generation

Generate code based on requirements:

```bash
soothe -p "Create a Python script that monitors a directory for new files and sends email notifications"
```

**What happens:**
1. Soothe plans the implementation
2. Creates file structure
3. Writes code with proper error handling
4. Adds documentation and comments

---

## Interactive Workflows

### Multi-Turn Conversations

The TUI maintains context across queries:

```
> Find all TODO comments in the codebase

✓ Found 23 TODO comments:
  - src/api/auth.py:42: TODO: Add rate limiting
  - src/services/user.py:128: TODO: Cache user data
  - ...

> Which one is most critical for security?

Based on the code analysis:
  src/api/auth.py:42 - "Add rate limiting"
  
This is critical because:
1. The auth endpoint has no throttling
2. Vulnerable to brute force attacks
3. Recent log analysis shows 500+ attempts/hour

Would you like me to implement rate limiting?
```

### Thread Management

Resume previous conversations:

```bash
# List recent threads
soothe loop list

# Continue a specific thread
soothe loop continue <thread-id>

# Or use the TUI's thread browser
soothe
# Press 't' to open thread browser
```

---

## Using Subagents

Soothe delegates tasks to specialized subagents:

### Explore Subagent

Filesystem search and analysis:

```bash
soothe -p "Find all configuration files and show which ones are unused"
```

### Plan Subagent

Task planning and decomposition:

```bash
soothe -p "Plan the migration from SQLite to PostgreSQL"
```

### Veritas Subagent

Research synthesis and fact-checking:

```bash
soothe -p "Verify the security claims in our authentication implementation against OWASP guidelines"
```

### Tacitus Subagent

Academic research:

```bash
soothe -p "Find recent papers on retrieval-augmented generation and summarize the state of the art"
```

### Browser Use Subagent

Web automation:

```bash
soothe -p "Go to the project's GitHub page and extract the open issues count"
```

> **Note**: Community subagents (e.g. `weaver`) and other community
> agents are available via the `soothe-plugins` package, not as core subagents.

---

## Slash Commands

Use slash commands in the TUI for quick actions:

```
> /help                    # Show all commands
> /clear                   # Clear current thread
> /threads                 # List threads
> /status                  # Show daemon status
> /quit                    # Exit Soothe
```

### Available Commands

| Command | Description |
|---------|-------------|
| `/help` | Show available commands |
| `/clear` | Clear current conversation |
| `/threads` | List recent threads |
| `/resume <id>` | Resume a thread |
| `/status` | Show daemon and agent status |
| `/config` | Show current configuration |
| `/quit` | Exit TUI |

---

## Configuration Quick Reference

### Environment Variables

```bash
# Required
export OPENAI_API_KEY=sk-your-key-here

# Optional
export SOOTHE_DEBUG=true              # Enable debug logging
```

### YAML Configuration

```yaml
# ~/.soothe/config/config.yml
providers:
  - name: openai
    provider_type: openai
    api_key: "${OPENAI_API_KEY}"

router:
  default: "openai:gpt-4o-mini"
  think: "openai:o3-mini"

filesystem_middleware:
  workspace_root: "."

observability:
  verbosity: normal
```

### Model Selection

Choose models based on task complexity:

```yaml
router:
  default: "openai:gpt-4o-mini"  # General tasks
  think: "openai:o3-mini"         # Complex reasoning, planning
  fast: "openai:gpt-4o-mini"      # Quick classifications
  embedding: "openai:text-embedding-3-small"
```

---

## Common Workflows

### 1. Project Exploration

```bash
# Understand project structure
soothe -p "Analyze the project architecture and create a diagram"

# Find dependencies
soothe -p "List all external dependencies and identify outdated ones"

# Code quality check
soothe -p "Run a code quality analysis and suggest improvements"
```

### 2. Documentation

```bash
# Generate API docs
soothe -p "Create API documentation from the FastAPI endpoints"

# Update README
soothe -p "Update README.md with recent changes from the git log"

# Create examples
soothe -p "Write usage examples for the main CLI commands"
```

### 3. Refactoring

```bash
# Identify duplicates
soothe -p "Find duplicate code patterns and suggest refactoring"

# Modernize code
soothe -p "Update Python 3.8 code to use Python 3.11 features"

# Security audit
soothe -p "Check for common security vulnerabilities and suggest fixes"
```

### 4. Testing

```bash
# Generate tests
soothe -p "Create unit tests for the authentication module"

# Find edge cases
soothe -p "Analyze error handling and identify missing edge cases"

# Coverage analysis
soothe -p "Identify code paths without test coverage"
```

---

## Using the Daemon

For long-running operations or remote access:

### Start the Daemon

```bash
# Start daemon
soothed start

# Check status
soothed doctor

# Stop daemon
soothed stop
```

### Daemon Benefits

- **Background Processing**: Run long tasks without keeping terminal open
- **WebSocket/HTTP API**: Remote access from other applications
- **Thread Persistence**: Maintain conversations across sessions
- **Resource Management**: Efficient resource sharing across threads

### Daemon CLI

```bash
# Start daemon
soothed start

# Start with debug logging
soothed start --debug

# Check status
soothed status

# View logs
soothed logs --follow

# Stop daemon
soothed stop

# Restart daemon
soothed restart
```

---

## Tips for Success

### 1. Be Specific

**Vague:**
```
soothe -p "Fix the code"
```

**Better:**
```
soothe -p "Fix the TypeError in src/api/auth.py line 42 where user_id is None"
```

### 2. Provide Context

**Without context:**
```
soothe -p "Create a function to process data"
```

**With context:**
```
soothe -p "Create a function to process CSV files from the data/ directory,
filter rows where status='active', and output JSON to results/"
```

### 3. Use Threads

For complex multi-step tasks:

```bash
# Start a thread for a complex project
soothe

> I need to refactor the authentication system to support OAuth2

> [Soothe creates a plan]

> [You discuss trade-offs]

> [Soothe implements changes]

> [You review and iterate]
```

### 4. Leverage Subagents

Let Soothe choose the right tool:

```
> Research the best practices for API rate limiting and implement them
```

Soothe will:
1. Use **Tacitus** to research best practices
2. Use **Plan** to design the implementation
3. Use **Explore** to find relevant code
4. Use **Core Agent** to implement changes

---

## Next Steps

Now that you're up and running:

1. **[Basic Concepts](Basic-Concepts.md)** - Understand Soothe's architecture
2. **[Configuration Guide](../configuration.md)** - Customize settings
3. **[CLI Reference](../cli-reference.md)** - Learn all commands
4. **[TUI Guide](../tui-guide.md)** - Master the terminal UI
5. **[Autonomous Mode](../autonomous-mode.md)** - Enable autonomous execution

---

## Troubleshooting

### Common Issues

**"API key not found"**
```bash
# Set your OpenAI API key
export OPENAI_API_KEY=sk-your-key-here
```

**"Config file not found"**
```bash
# Start the daemon to auto-create ~/.soothe/ directory structure
soothed start
```

**"Command not found: soothe"**
```bash
# Ensure soothe-cli is installed
pip install -U soothe-cli
# Check PATH includes pip bin directory
echo $PATH
```

**Daemon not responding**
```bash
# Check daemon status
soothed status
# Restart if needed
soothed restart
```

For more help, see the [Troubleshooting Guide](../troubleshooting.md).

---

## Getting Help

- **Documentation**: [Wiki](../index.md)
- **Issues**: [GitHub Issues](https://github.com/mirasoth/soothe/issues)
- **Architecture**: [Architecture Overview](../architecture/index.md)