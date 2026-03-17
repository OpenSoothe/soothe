# Check Categories Reference

This document provides detailed specifications for each health check item, organized by category.

## Category 1: Core Infrastructure

### Check: Daemon Process Status
- **What**: Verify Soothe daemon is running and socket is accepting connections
- **How**: Run `scripts/check_daemon.py` or use `SootheDaemon.is_running()`
- **Expected**:
  - PID file exists at `~/.soothe/soothe.pid`
  - Process is alive (verify with `os.kill(pid, 0)`)
  - Unix socket at `~/.soothe/soothe.sock` accepts connections
  - No stale lock files
- **On Failure**:
  - Check if `~/.soothe/soothe.pid` contains a valid PID
  - Verify no stale locks: `ls -la ~/.soothe/soothe.pid`
  - Restart daemon: `soothe --daemon`
  - Check logs: `~/.soothe/logs/daemon.log`

### Check: PID File Validity
- **What**: Ensure PID file exists and contains a valid running process ID
- **How**: Read `~/.soothe/soothe.pid`, parse PID, verify with `os.kill(pid, 0)`
- **Expected**: PID file exists, contains integer, process responds to signal 0
- **On Failure**:
  - If PID file missing but daemon running, daemon may have been started incorrectly
  - If PID exists but process not found, daemon crashed without cleanup
  - Remove stale PID file: `rm ~/.soothe/soothe.pid`
  - Restart daemon

### Check: Socket Connectivity
- **What**: Verify Unix domain socket accepts connections
- **How**: Attempt to connect to `~/.soothe/soothe.sock` with timeout
- **Expected**: Socket exists, connection succeeds within 1 second
- **On Failure**:
  - Check socket file permissions: `ls -la ~/.soothe/soothe.sock`
  - Verify no stale socket: `rm ~/.soothe/soothe.sock` if daemon not running
  - Restart daemon

### Check: Model Provider Configuration
- **What**: Validate model provider configs have required fields and API keys
- **How**: Load config, check each provider has name and resolved API key
- **Expected**: All providers have valid API keys (no unresolved `${ENV_VAR}` placeholders)
- **On Failure**:
  - Check `~/.soothe/config/config.yml` providers section
  - Verify environment variables are set: `echo $OPENAI_API_KEY`
  - Ensure API keys are valid (not expired or revoked)

## Category 2: Protocol Backends

### Check: Context Protocol Backend
- **What**: Validate context protocol backends can be imported and initialized
- **How**:
  - Import from `soothe.backends.context`
  - Check vector store and keyword store backends
  - Verify required methods exist
- **Expected**: Imports succeed, backends have required interface methods
- **On Failure**:
  - Check dependencies: `pip install -r requirements.txt`
  - Verify config context section is valid
  - Check for import errors in logs

### Check: Memory Protocol Backend
- **What**: Validate memory protocol backends for vector and keyword storage
- **How**: Import from `soothe.backends.memory`, verify interface
- **Expected**: Vector and keyword memory backends load successfully
- **On Failure**:
  - Check config memory section
  - Verify embedding model configuration
  - Ensure vector store dependencies installed

### Check: Planner Protocol Backend
- **What**: Validate planner backends (direct, subagent, claude)
- **How**: Import from `soothe.backends.planning`, check each backend
- **Expected**: All configured planner backends initialize correctly
- **On Failure**:
  - Check config planner section
  - Verify Claude API access if using claude planner
  - Ensure subagent dependencies installed if using subagent planner

### Check: Policy Protocol Backend
- **What**: Validate policy backend loads and enforces rules
- **How**: Import from `soothe.backends.policy`, verify config-driven policy
- **Expected**: Policy backend loads rules from config successfully
- **On Failure**:
  - Check config policy section syntax
  - Verify policy rules are valid YAML
  - Ensure no conflicting rules

### Check: Durability Protocol Backend
- **What**: Validate durability backends (JSON, RocksDB, PostgreSQL)
- **How**: Import from `soothe.backends.durability`, test configured backend
- **Expected**: Configured durability backend initializes and can perform basic operations
- **On Failure**:
  - JSON: Check file permissions and disk space
  - RocksDB: Verify `rocksdb` package installed, check data directory
  - PostgreSQL: Verify database connection, check table schema
  - See persistence layer checks for details

### Check: Vector Store Protocol Backend
- **What**: Validate vector store backends (in-memory, pgvector, weaviate)
- **How**: Import from `soothe.backends.vector_store`, test configured backend
- **Expected**: Vector store initializes, can create/test collections
- **On Failure**:
  - In-memory: Should always work
  - pgvector: Check PostgreSQL extension installed, connection valid
  - weaviate: Check Weaviate service running, connection config valid

### Check: Remote Agent Protocol Backend
- **What**: Validate remote agent backend (LangGraph)
- **How**: Import from `soothe.backends.remote`, test LangGraph connection
- **Expected**: Remote agent backend initializes, can reach configured endpoints
- **On Failure**:
  - Check LangGraph service running
  - Verify network connectivity to configured endpoints
  - Check authentication credentials

## Category 3: Persistence Layer

### Check: PostgreSQL Connectivity
- **What**: Verify PostgreSQL database connection and schema
- **How**:
  - Read database config from `config.persistence.postgresql`
  - Attempt connection using `asyncpg` or `psycopg2`
  - Verify required tables exist
- **Expected**:
  - Connection succeeds within timeout
  - Tables exist: `threads`, `checkpoints`, `writes` (or configured names)
  - User has SELECT, INSERT, UPDATE, DELETE permissions
- **On Failure**:
  - Check database connection string in config
  - Verify PostgreSQL service running: `systemctl status postgresql`
  - Check database exists: `psql -l`
  - Verify user permissions: `psql -U <user> -d <database>`
  - Run schema migrations if needed

### Check: RocksDB Availability
- **What**: Verify RocksDB data directory exists and is writable
- **How**:
  - Check configured data directory path
  - Verify directory exists or can be created
  - Test write/read operations
- **Expected**:
  - Directory exists or parent is writable
  - `rocksdb` Python package installed
  - Can create/write/read test file in directory
- **On Failure**:
  - Install RocksDB: `pip install python-rocksdb`
  - Create data directory: `mkdir -p ~/.soothe/data/rocksdb`
  - Check disk space: `df -h ~/.soothe`
  - Verify permissions: `ls -la ~/.soothe/data`

### Check: File System Permissions
- **What**: Verify Soothe home directory is accessible and writable
- **How**:
  - Check `~/.soothe/` exists
  - Test create/write/read in subdirectories
  - Check available disk space
- **Expected**:
  - `~/.soothe/` exists with correct permissions (user rwx)
  - Subdirectories: `logs/`, `threads/`, `config/`
  - At least 100MB free disk space
- **On Failure**:
  - Create directory: `mkdir -p ~/.soothe/{logs,threads,config,data}`
  - Fix permissions: `chmod 700 ~/.soothe`
  - Free disk space or move to larger partition

## Category 4: Subagent System

### Check: Subagent Module Imports
- **What**: Verify all subagent modules can be imported
- **How**:
  - Import from `soothe.subagents.generated`
  - Check each subagent module loads without errors
  - Verify subagent registry is populated
- **Expected**: All generated subagent modules import successfully
- **On Failure**:
  - Check subagent generation: `soothe generate-subagents`
  - Verify `src/soothe/subagents/generated/` exists
  - Check for missing dependencies in subagent implementations

### Check: External Subagent Dependencies
- **What**: Verify optional dependencies for specific subagents
- **How**:
  - Check browser-use subagent: `browser_use` package
  - Check tavily subagent: `tavily-python` package
  - Check other subagent dependencies as applicable
- **Expected**: Required packages installed for configured subagents
- **On Failure**:
  - Install missing packages: `pip install browser-use tavily-python`
  - Or disable subagent in config if not needed

### Check: Generated Agent Registry
- **What**: Verify generated agent registry file exists and is valid
- **How**: Check `src/soothe/subagents/generated/__init__.py` or registry file
- **Expected**: Registry file exists, contains valid agent definitions
- **On Failure**:
  - Re-run subagent generation: `soothe generate-subagents`
  - Check config subagents section for syntax errors
  - Verify subagent templates are valid

## Category 5: External Integrations

### Check: MCP Server Connectivity
- **What**: Verify configured MCP servers are reachable
- **How**:
  - Read MCP server config
  - Attempt to connect to each configured server
  - Test basic protocol handshake
- **Expected**: All configured MCP servers respond to connection attempts
- **On Failure**:
  - Check MCP server process is running
  - Verify server endpoint configuration
  - Check network connectivity and firewall rules
  - Note: MCP server failure is a warning, not critical

### Check: Browser Runtime (Chrome/Chromium)
- **What**: Verify Chrome or Chromium is installed and chromedriver matches version
- **How**: Run `scripts/check_chrome.sh` or equivalent checks
- **Expected**:
  - Chrome or Chromium installed
  - chromedriver version matches browser major version
  - chromedriver in PATH or configured location
- **On Failure**:
  - Run `scripts/check_chrome.sh` to auto-install matching chromedriver
  - Or install manually: `brew install --cask google-chrome`
  - Note: Only required for browser automation features

### Check: External API Connectivity
- **What**: Test connectivity to external APIs (OpenAI, Google, Tavily, etc.)
- **How**:
  - Read API keys from config or environment
  - Make minimal API call to each service
  - Check response status
- **Expected**: API calls succeed or return auth errors (indicates connectivity)
- **On Failure**:
  - Check API keys are valid: `echo $OPENAI_API_KEY`
  - Verify network connectivity: `curl -I https://api.openai.com`
  - Check for rate limiting or service outages
  - Note: API failures are warnings if not actively used

### Check: Search Service Connectivity (Tavily, Serper, Jina)
- **What**: Verify search service APIs are accessible
- **How**:
  - Test Tavily API with minimal query
  - Test Serper API with minimal query
  - Test Jina API if configured
- **Expected**: APIs respond (even if rate limited or auth required)
- **On Failure**:
  - Check API keys in config
  - Verify service status pages
  - Note: Only critical if search features are actively used

## Category 6: Runtime Health

### Check: Thread Management
- **What**: Verify thread state can be created, persisted, and loaded
- **How**:
  - Attempt to create a test thread with SootheRunner
  - Verify thread ID is generated
  - Check thread can be loaded from persistence
- **Expected**: Thread creation succeeds, thread ID valid, persistence works
- **On Failure**:
  - Check persistence backend configuration
  - Verify thread logging directory permissions
  - Check for disk space issues

### Check: Resource Cleanup
- **What**: Verify cleanup handlers are registered and functional
- **How**:
  - Check for stale temporary files
  - Verify cleanup runs on daemon shutdown
  - Check thread log cleanup based on retention policy
- **Expected**: No excessive stale files, cleanup runs successfully
- **On Failure**:
  - Manually clean temp files: `rm ~/.soothe/tmp/*`
  - Check cleanup configuration in config
  - Verify retention policy is sensible

### Check: Logging System
- **What**: Verify logging configuration and log file accessibility
- **How**:
  - Check log directory exists and is writable
  - Verify log files are being created
  - Check log rotation is working
- **Expected**:
  - `~/.soothe/logs/` directory exists
  - Log files created: `daemon.log`, `soothe.log`
  - Log rotation prevents excessive file sizes
- **On Failure**:
  - Create log directory: `mkdir -p ~/.soothe/logs`
  - Check disk space
  - Verify log configuration in config file
  - Check file permissions

## Appendix: Check Priority Levels

Checks are categorized by priority:

- **Critical**: Must pass for Soothe to function (daemon, persistence, config)
- **Important**: Should pass for full functionality (protocols, subagents)
- **Optional**: Nice to have but not required (external APIs, browser)

The health check exit code reflects the highest priority failure:
- Exit 2: Any critical check failed
- Exit 1: Only important/optional checks failed
- Exit 0: All checks passed
