# IG-423: CodeInterpreterMiddleware Integration

## Goal
Integrate Deep Agents' new `CodeInterpreterMiddleware` into Soothe to enable embedded QuickJS interpreter for programmatic tool calling and stateful code execution within the agent loop.

## Background
Deep Agents v0.6 introduced `CodeInterpreterMiddleware` which provides:
- Embedded QuickJS runtime for TypeScript/JavaScript execution
- Persistent interpreter state across eval calls (REPL-like behavior)
- Programmatic Tool Calling (PTC) via `tools.*` namespace
- Reduced token usage (up to 35% in early testing)
- Sandboxed execution with explicit capability bridges

Reference: https://www.langchain.com/blog/give-your-agents-an-interpreter

## Scope

### Files to Modify
1. `packages/soothe/src/soothe/config/models.py` - Add `CodeInterpreterConfig`
2. `packages/soothe/src/soothe/config/settings.py` - Add config field reference
3. `packages/soothe/src/soothe/middleware/code_interpreter.py` - New middleware module
4. `packages/soothe/src/soothe/middleware/__init__.py` - Export new middleware
5. `packages/soothe/src/soothe/middleware/_builder.py` - Add to middleware stack
6. `config/config.template.yml` - Add interpreter configuration template
7. `config/config.dev.yml` - Add dev defaults

### Configuration Schema
```yaml
interpreter:
  enabled: false  # Disabled by default (opt-in feature)
  ptc_allowlist: []  # Tools exposed to interpreter via tools.* namespace
  memory_limit_mb: 128  # Interpreter memory limit
  timeout_seconds: 30  # Per-eval timeout
  max_ptc_calls: 50  # Maximum programmatic tool calls per eval
  max_result_size: 10000  # Maximum result size in characters
  console_capture: true  # Capture console.log output
  snapshot_between_turns: false  # Preserve state between conversation turns
```

## Implementation Plan

### Phase 1: Configuration
- Add `CodeInterpreterConfig` Pydantic model to `config/models.py`
- Add `interpreter: CodeInterpreterConfig` field to `SootheConfig`
- Update template and dev config files

### Phase 2: Middleware Implementation
- Create `CodeInterpreterMiddleware` wrapping `langchain_quickjs.CodeInterpreterMiddleware`
- Handle configuration mapping from Soothe config to deepagents middleware
- Add proper error handling and logging

### Phase 3: Integration
- Add middleware to stack builder in `_builder.py`
- Position in middleware stack (after filesystem, before per-turn model)

### Phase 4: Verification
- Run `./scripts/verify_finally.sh`
- Ensure no breaking changes to existing functionality

## Design Decisions

1. **Disabled by default**: The interpreter is an advanced feature that should be opt-in
2. **Empty PTC allowlist by default**: Security-first approach - tools must be explicitly allowed
3. **Separate from sandbox**: Interpreter is distinct from shell/execution sandbox
4. **QuickJS dependency**: Requires `langchain-quickjs` package (optional dependency)

## Status

- [x] Implementation Guide created
- [ ] Configuration models added
- [ ] Middleware module created
- [ ] Middleware stack integration
- [ ] Config templates updated
- [ ] Verification passed
