# Development Process

> Binding rules for how work is planned, implemented, and verified. Compliance is mandatory.

## Design Docs
- **Substantial work**: Create a design doc in `docs/impl/` (`IG-XXX-brief-title.md`)
- **Minor changes**: No design doc — commit/PR context suffices

## Ecosystem First
Check `langchain-core`, `langchain-community`, `deepagents` before implementing anything:
- Tools: `BaseTool`, `@tool` · Subagents: `SubAgent`, `CompiledSubAgent` · MCP: `langchain-mcp-adapters` · Memory: `deepagents.MemoryMiddleware`

## Test Location
Tests go in `packages/<pkg>/tests/unit/` or `tests/integration/` — NOT root `tests/`.

## Verification Required
`./scripts/verify_finally.sh` before ANY commit. Zero lint errors, all tests pass.

## After Code Impl: Cleanse → Verify → Fix (MUST)
Before marking work done, every time:
1. **Ask user** whether to cleanse legacy code, compat shims, and dead code related to the change.
2. **Cleanse** (if approved) — remove superseded helpers, unused exports, duplicate paths, compat shims, stale tests/docs. Deletion/consolidation only; **no behavior rewrites**.
3. **Verify** — `./scripts/verify_finally.sh`
4. **Fix to green** — lint, format, tests, vulture. Re-cleanse if fixes leave new dead code, then re-verify until green.

## DO NOT Cheat Tests
Fix the implementation, not test expectations. "Passing tests" ≠ "Working correctly."

## Workflow
1. **Plan**: Explore codebase → ask when alternatives exist → ExitPlanMode for approval
2. **Implement**: Place code per package-boundaries rules → check ecosystem → follow patterns → `make lint`
3. **Cleanse → Verify → Fix** (Critical Rule 6 — MUST after every code impl): remove related legacy/dead code **without changing existing functionality**, then `./scripts/verify_finally.sh`, then fix until green
4. **GitHub Actions / `gh` CLI**: Use the `GH_TOKEN` env var
