# Soothe Wiki

Welcome to the Soothe end-user wiki. This directory contains comprehensive guides organized by user journey.

## Wiki Index

### 🚀 Getting Started

- **[Getting Started Guide](getting-started.md)** - Install, configure, and run your first session
  - Installation (pip, source)
  - API key setup
  - First steps (interactive TUI, headless mode)
  - Resume sessions

- **[CLI Reference](cli-reference.md)** - Complete command-line interface documentation
  - All CLI commands and options
  - Run, autopilot, thread, server, auth, config, agent commands
  - Examples and use cases

- **[TUI Guide](tui-guide.md)** - Terminal UI usage, slash commands, and keyboard shortcuts
  - Interface overview
  - Slash commands table
  - Keyboard shortcuts
  - Subagent routing

### 📖 User Guides

- **[Specialized Subagents](subagents.md)** - Overview of Browser, Claude, Skillify, and Weaver
  - Subagent capabilities
  - Installation requirements
  - Usage with slash commands and prefix routing
  - Configuration

- **[Autonomous Mode](autonomous-mode.md)** - Enable autonomous iteration for complex tasks
  - What is autonomous mode
  - When to use it
  - How to enable (CLI, TUI)
  - Configuration and monitoring

- **[Thread Management](thread-management.md)** - Work with conversation threads
  - What are threads
  - Listing, resuming, archiving threads
  - Thread lifecycle
  - Export threads

### 🔧 Configuration & Management

- **[Configuration Guide](configuration.md)** - Environment variables, YAML config, and model routing
  - Configuration methods
  - Essential settings
  - Model router
  - Optional extras

- **[Daemon Management](daemon-management.md)** - Manage the Soothe daemon lifecycle
  - Server lifecycle (start, stop, status, attach)
  - Detached execution
  - Logs and monitoring

- **[Multi-Transport Setup](multi-transport.md)** - Configure Unix Socket, WebSocket, and HTTP REST
  - Transport overview
  - When to enable each transport
  - Configuration examples
  - Use cases

- **[Authentication](authentication.md)** - API keys, JWT, and security model
  - Creating and managing API keys
  - JWT authentication
  - Security model
  - Integration examples

### 🛠️ Troubleshooting & Advanced

- **[Troubleshooting Guide](troubleshooting.md)** - Common issues and solutions
  - API key issues
  - Subagent problems
  - Connection errors
  - Authentication errors
  - Performance issues
  - Debug mode

## Navigation

Each wiki page includes cross-links to related guides. Start with the [Getting Started Guide](getting-started.md) if you're new to Soothe, or browse the specific guides based on your needs.

For technical documentation, see the main [User Guide](../user_guide.md) which links to RFCs and implementation guides.