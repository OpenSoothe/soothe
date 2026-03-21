# Soothe

[![Python](https://img.shields.io/pypi/pyversions/soothe)](https://pypi.org/project/soothe/)
[![PyPI Version](https://img.shields.io/pypi/v/soothe)](https://pypi.org/project/soothe/)
[![License](https://img.shields.io/github/license/caesar0301/Soothe)](https://github.com/caesar0301/Soothe/blob/main/LICENSE)
[![GitHub Stars](https://img.shields.io/github/stars/caesar0301/Soothe)](https://github.com/caesar0301/Soothe)
[![Ask DeepWiki](https://deepwiki.com/badge.svg)](https://deepwiki.com/caesar0301/Soothe)

Your intelligent, always-available AI assistant that works autonomously on complex tasks.

## What is Soothe?

Soothe is an AI-powered agent that doesn't just answer questions—it takes action. Unlike traditional chatbots that stop at providing information, Soothe can execute multi-step workflows, conduct research, browse the web, write code, and manage long-running tasks autonomously.

Think of Soothe as a tireless digital colleague who can:
- Research topics across the web and synthesize findings
- Execute complex workflows that span hours or days
- Learn from past interactions and remember important context
- Work independently while you focus on other things
- Coordinate multiple specialized tools and agents

## Design Philosophy

### Autonomous Intelligence

Soothe is built for **autonomous operation**. Once you give it a goal, it can:
- Break down complex objectives into manageable steps
- Execute those steps without constant supervision
- Reflect on results and adjust its approach
- Continue working across multiple sessions if needed

You don't need to micromanage every step. Soothe handles the details while keeping you informed of progress.

### Persistent Memory

Soothe remembers. It maintains:
- **Context within conversations**: Accumulates knowledge as it works
- **Memory across sessions**: Recalls important findings from past interactions
- **Goal tracking**: Keeps track of long-term objectives and their status

This means you can have ongoing, evolving conversations without repeating yourself.

### Privacy-First Design

Your data stays under your control:
- Browser automation runs locally with privacy-first defaults
- No mandatory cloud services or telemetry
- Configurable data persistence on your own infrastructure
- API keys and secrets managed through environment variables

### Extensible Architecture

Soothe grows with your needs:
- Built-in tools for web search, browsing, code execution, and more
- Specialized subagents for planning, research, and automation
- Integration with external services via MCP (Model Context Protocol)
- Customizable policies for security and access control

## What Can Soothe Do?

### Research & Analysis
- Search the web and synthesize information from multiple sources
- Analyze documents, codebases, and datasets
- Generate reports and summaries
- Track developments over time

### Task Automation
- Execute multi-step workflows autonomously
- Browse websites, fill forms, and extract data
- Run code and scripts
- Manage files and directories

### Planning & Execution
- Break down complex goals into actionable plans
- Execute plans step-by-step with progress tracking
- Adapt plans based on results
- Handle dependencies and priorities

### Long-Running Operations
- Work on tasks that span hours or days
- Resume work after interruptions
- Maintain state across sessions
- Operate in the background while you do other things

## Getting Started

### Quick Start

1. **Install Soothe**:
   ```bash
   pip install soothe
   ```

2. **Set your API key**:
   ```bash
   export OPENAI_API_KEY=sk-your-key-here
   ```

3. **Run Soothe**:
   ```bash
   soothe run
   ```

That's it! You'll see an interactive terminal interface where you can start giving Soothe tasks.

## Learn More

- **[User Guide](docs/user_guide.md)**: Complete guide for using Soothe
- **[Documentation](docs/)**: Design specifications and implementation guides
- **[Examples](docs/user_guide.md#examples)**: More usage examples and patterns

## License

MIT