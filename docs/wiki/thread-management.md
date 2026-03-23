# Thread Management

Work with conversation threads in Soothe.

## What Are Threads?

Threads are conversation sessions. Each thread maintains:
- Your conversation history
- Context and accumulated knowledge
- Memory of important findings
- Task plans and progress

Threads enable you to:
- Resume previous work
- Maintain context across sessions
- Track progress on long-running tasks
- Organize different projects or topics

## Listing Threads

View all your threads:

```bash
# CLI
soothe thread list
```

**Output**:

**Output**:
```
Thread ID    Status     Created              Last Active          Messages
abc123       active     2026-03-20 10:00    2026-03-22 14:30    45
def456       active     2026-03-18 09:15    2026-03-21 16:20    28
ghi789       archived   2026-03-15 11:00    2026-03-15 18:45    62
```

## Resuming Threads

Continue a previous conversation:

```bash
# CLI - Resume a specific thread
soothe thread continue abc123

# CLI - Resume last active thread
soothe thread continue

# Resume via running daemon
soothe thread continue --daemon abc123

# Start a new thread
soothe thread continue --new

# In TUI - Interactive thread selection
/resume
```

The TUI `/resume` command shows an interactive list of recent threads to select from.

When you resume a thread:
- Full conversation history is restored
- Context and memory are available
- Previous plans can be continued
- You can pick up where you left off

## Thread Details

View detailed information about a thread:

```bash
soothe thread show abc123
```

**Output**:
```
Thread ID: abc123
Status: active
Created: 2026-03-20 10:00:00
Last Active: 2026-03-22 14:30:15
Messages: 45

Context Stats:
  Documents: 12
  Total Tokens: 8,500

Memory Stats:
  Entries: 23
  Topics: code analysis, API design

Plan Status:
  Steps Completed: 8/10
  Current Step: Testing authentication flow
```

## Archiving Threads

Clean up old threads without deleting them:

```bash
# CLI
soothe thread archive abc123
```

Archived threads:
- Are hidden from active thread lists
- Can still be resumed if needed
- Free up context resources
- Preserve conversation history

## Thread Statistics

View execution statistics for a thread:

```bash
soothe thread stats abc123
```

**Output**:
```
Thread: abc123
Messages: 45
Events: 128
Artifacts: 12
Errors: 2
Last Error: Connection timeout during step 3
```

## Thread Tags

Add or remove tags to organize threads:

```bash
# Add tags
soothe thread tag abc123 research analysis

# Remove tags
soothe thread tag abc123 research --remove
```

Tags help you categorize and find threads later.

## Deleting Threads

Permanently remove a thread:

```bash
soothe thread delete abc123
```

**Warning**: This action cannot be undone. All conversation history, context, and memory will be lost.

## Exporting Threads

Export a thread to a file:

```bash
# Export as JSON
soothe thread export abc123 --output thread_abc123.json

# Export as markdown
soothe thread export abc123 --output thread_abc123.md --format markdown
```

**Export includes**:
- All messages
- Metadata (timestamps, status)
- Plan information
- Context and memory references

## Thread Lifecycle

1. **Creation**: New thread created when you start a conversation
2. **Active**: Thread is in use, context and memory accumulate
3. **Suspended**: Thread paused (e.g., when you detach TUI)
4. **Archived**: Thread hidden but preserved
5. **Deleted**: Thread permanently removed

## Storage Location

Threads are stored in the Soothe home directory:

```bash
~/.soothe/threads/
├── abc123/
│   ├── messages.json
│   ├── context.json
│   ├── memory.json
│   └── metadata.json
├── def456/
└── ...
```

## Best Practices

1. **Name Your Threads**: Use descriptive names for important threads
   ```bash
   # First message sets context
   "I'm working on the authentication module refactor"
   ```

2. **Archive Old Threads**: Keep thread list clean by archiving completed work

3. **Export Important Threads**: Save valuable conversations externally

4. **Resume Context**: Continue threads instead of starting fresh for related tasks

5. **Clean Up**: Periodically delete threads you no longer need

## Related Guides

- [CLI Reference](cli-reference.md) - Thread commands
- [TUI Guide](tui-guide.md) - Thread slash commands
- [Configuration Guide](configuration.md) - Thread storage settings