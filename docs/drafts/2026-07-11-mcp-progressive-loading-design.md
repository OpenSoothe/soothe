# Design Draft: MCP Progressive Loading (Tools/Skills Parity)

**Date**: 2026-07-11  
**Status**: Approved — incorporated into RFC-412 (2026-07-11 revision)  
**Related**: RFC-412 (MCP Management), RFC-105 (Progressive Skill Loading), RFC-101 (Tool Interface)  
**Companion impl**: IG-448 (MCP management — partial)  
**Problem**: RFC-412 progressive disclosure is spec-complete but runtime-incomplete; deferred MCP tools are listed in the prompt but not bound as callable tools.

---

## 1. Problem Statement

Soothe has three progressive-disclosure subsystems:

| Subsystem | Listing | Discovery | Activation |
|-----------|---------|-----------|------------|
| **Builtin tools** | `<AVAILABLE_TOOLS>` | `search_tools` | `ProgressiveToolMiddleware` promotes + re-binds tool array |
| **Skills** | `<AVAILABLE_SKILLS>` | `search_skills` | `invoke_skill` loads body into `<SKILL_CONTEXT>` |
| **MCP tools** | `<AVAILABLE_MCP_TOOLS>` ✅ | `mcp_tool_search` ❌ | promote + bind ❌ |

MCP currently implements **Stage 1 only** (budgeted metadata listing). A server with `defer: true` (the default) has its tools:

1. Fetched and stored in `MCPRegistry._tools`
2. Listed as name/description text in `<AVAILABLE_MCP_TOOLS>`
3. **Not** injected into the agent's `tools=` array

The model sees `mcp__github__create_issue` in the prompt but cannot call it — the tool schema is absent. `invoked_mcp_tools` is written by `MCPToolSearchMiddleware` but never read to promote tools. `mcp_tool_search` does not exist.

This design closes the gap by mirroring the **builtin tools** pattern (not skills), because MCP tools are callable `BaseTool` instances, not injectable instruction bodies.

---

## 2. Design Goals

1. **Tools-parity runtime** — deferred MCP tools follow the same `search → promote → bind` loop as `ProgressiveToolMiddleware`.
2. **Bounded turn-0 cost** — only `defer: false` server tools bound at cold start; deferred tools appear as budgeted metadata deltas.
3. **Delta-only listing** — a tool announced in `<AVAILABLE_MCP_TOOLS>` is never re-listed unless evicted by compaction.
4. **Durable per-thread state** — activation survives iteration boundaries, reconnect, and resume (same snapshot pattern as RFC-105 / progressive tools).
5. **Separate discovery surface** — `search_mcp_tools` is distinct from `search_tools` and `search_skills` (domain separation, clearer tool descriptions).
6. **Minimal diff** — reuse existing `MCPRegistry`, `format_mcp_tools_within_budget`, `MCPToolDescriptor`; replace/extend the stub middleware.

## 3. Non-Goals

- Unified `search_everything` across builtin/MCP/skills (rejected: couples unrelated catalogs).
- Semantic/vector search for MCP tools (deferred; substring match is sufficient for v1).
- Turn-0 intent prefetch for MCP (deferred; MCP tool names are less predictable than skill names).
- MCP prompt/resource progressive loading (prompts are slash commands; resources use `mcp_resources_list/read` — already eager).
- Policy gating implementation (RFC-412 separate concern; design leaves hook points).
- Per-tool `_meta['anthropic/alwaysLoad']` from MCP SDK (deferred; server-level `defer` is sufficient for v1).

---

## 4. Approaches Considered

### A. Tools-parity middleware (recommended)

New `ProgressiveMCPRegistry` + `MCPActivationMiddleware` parallel to `ProgressiveToolRegistry` + `ProgressiveToolMiddleware`:

- Full MCP tool catalog registered at agent build
- Middleware binds `always_loaded ∪ promoted` per model hop
- `search_mcp_tools` promotes matches
- Direct `mcp__*` invocation promotes on success

**Pros**: Symmetric with existing code; isolated; testable; matches RFC-412 intent.  
**Cons**: One more middleware + registry module.

### B. Extend `search_tools` to include MCP

Single search tool queries builtin + MCP deferred catalogs.

**Pros**: Fewer tools in core tier.  
**Cons**: Couples domains; muddies tool descriptions; harder policy filtering; breaks "exact tool name" guidance.

### C. Eager-bind all MCP tools, progressive prompt only

All MCP `BaseTool` schemas always in `tools=`; only descriptions are budgeted in prompt.

**Pros**: Simplest runtime.  
**Cons**: Defeats the primary motivation — MCP servers expose hundreds of tool schemas that bloat context and hurt selection accuracy.

**Recommendation**: **Approach A**.

---

## 5. Architecture

### 5.1 Component overview

```
┌─────────────────────────────────────────────────────────────┐
│  MCPRegistry (daemon singleton, existing)                   │
│  - _tools[server] → list[BaseTool]   (full catalog)       │
│  - always_loaded_tools() / deferred_tools()                 │
└──────────────────────────┬──────────────────────────────────┘
                           │
         ┌─────────────────┴─────────────────┐
         ▼                                   ▼
┌─────────────────────────┐     ┌──────────────────────────────┐
│ ProgressiveMCPRegistry  │     │ MCPActivationMiddleware      │
│ (new, stateless facade) │     │ (replaces MCPToolSearchMW)   │
│                         │     │                              │
│ partition core/deferred │     │ awrap_tool_call:             │
│ new_for_thread / mark_* │     │   search_mcp_tools handler   │
│ search_deferred         │     │   promote on mcp__* invoke   │
│ bound_tools             │     │ awrap_model_call:             │
└──────────┬──────────────┘     │   override tools= bound set  │
           │                    └──────────────┬───────────────┘
           ▼                                   │
┌─────────────────────────┐                    │
│ SystemPromptMiddleware  │◄───────────────────┘
│ ._compose_mcp_tools_block                   │
│ writes <AVAILABLE_MCP_TOOLS> (static tier)   │
└─────────────────────────┘
           │
           ▼
┌─────────────────────────┐
│ state["mcp_activation"] │
│ LoopState snapshot      │
└─────────────────────────┘
```

### 5.2 Symmetry table (target end state)

| Concern | Builtin tools | Skills | MCP tools |
|---------|---------------|--------|-----------|
| Registry | `ProgressiveToolRegistry` | `ProgressiveSkillRegistry` | `ProgressiveMCPRegistry` |
| Middleware | `ProgressiveToolMiddleware` | `SkillActivationMiddleware` | `MCPActivationMiddleware` |
| State key | `tool_activation` | `skill_activation` | `mcp_activation` |
| State shape | `{sent, promoted}` | `{sent, activated, invoked, invoked_bodies, ...}` | `{sent, promoted}` |
| Discovery tool | `search_tools` | `search_skills` | `search_mcp_tools` |
| Activation | bind `BaseTool` | inject `<SKILL_CONTEXT>` | bind `BaseTool` |
| Prompt block | `<AVAILABLE_TOOLS>` | `<AVAILABLE_SKILLS>` | `<AVAILABLE_MCP_TOOLS>` |
| Config | `progressive_tools` | `progressive_skills` | `progressive_mcp` |
| Core tier | `core_tools` config | `core_skills` + builtin | `defer: false` servers |

---

## 6. Type Definitions

### 6.1 `mcp_activation` (graph state)

Replace flat `sent_mcp_tool_names` / `invoked_mcp_tools` dict with a unified dict matching tools:

```python
# state["mcp_activation"]
{
    "sent": set[str],      # mangled names already emitted in <AVAILABLE_MCP_TOOLS>
    "promoted": set[str],  # mangled names bound in tools= for this thread
}
```

LangGraph reducer: `merge_mcp_activation` — union `sent` and `promoted` (same as `merge_tool_activation`).

### 6.2 LoopState snapshot (durability)

Migrate existing fields to match:

```python
# Deprecate (migrate in one PR):
#   sent_mcp_tool_names → mcp_activation.sent
#   invoked_mcp_tools: dict → mcp_activation.promoted: set[str]

# New canonical fields:
mcp_activation_sent: set[str] = Field(default_factory=set)
mcp_activation_promoted: set[str] = Field(default_factory=set)
disabled_mcp_servers: set[str] = Field(default_factory=set)  # unchanged
cached_mcp_resources: dict[str, str] = Field(default_factory=dict)  # unchanged
```

Executor rehydrate/snapshot copies `mcp_activation` ↔ LoopState fields at iteration boundaries (same as `tool_activation` / `skill_activation`).

### 6.3 `ProgressiveMCPConfig`

Budget tunables only (`budget_pct`, listing caps). `search_mcp_tools` is always registered when the MCP registry has deferred tools — no separate enable flag.

---

## 7. `ProgressiveMCPRegistry` (new)

Location: `packages/soothe/src/soothe/mcp/progressive_registry.py`

Stateless facade; mirrors `ProgressiveToolRegistry`:

```python
class ProgressiveMCPRegistry:
    def __init__(self, always_loaded_names: frozenset[str]) -> None: ...

    @staticmethod
    def init_activation_state() -> dict[str, set[str]]: ...

    def partition(
        self, descriptors: Sequence[MCPToolDescriptor]
    ) -> tuple[list[MCPToolDescriptor], list[MCPToolDescriptor]]:
        """Core = is_essential (defer=False server); deferred = rest."""

    def bound_tool_names(self, activation: dict) -> set[str]:
        """always_loaded_names ∪ promoted"""

    def bound_tools(self, tools: Sequence[BaseTool], activation: dict) -> list[BaseTool]: ...

    def new_for_thread(self, activation, deferred) -> list[MCPToolDescriptor]:
        """Delta: deferred not in sent and not in promoted."""

    def mark_sent(self, activation, names: Iterable[str]) -> None: ...
    def mark_promoted(self, activation, names: Iterable[str]) -> None: ...

    def search_deferred(
        self, query: str, deferred: Sequence[MCPToolDescriptor], *, limit: int = 10
    ) -> list[MCPToolDescriptor]:
        """Substring match on mangled name + bare_name + description + server."""
```

`always_loaded_names` is computed at middleware init from `registry.always_loaded_tools()`.

---

## 8. `MCPActivationMiddleware` (replaces `MCPToolSearchMiddleware`)

Location: `packages/soothe/src/soothe/middleware/mcp_activation.py`

Rename for accuracy; expand responsibilities to match `ProgressiveToolMiddleware`.

### 8.1 Init

```python
def __init__(self, mcp_registry: MCPRegistry, config: SootheConfig) -> None:
    self._registry = mcp_registry
    self._config = config
    core_names = frozenset(t.name for t in mcp_registry.always_loaded_tools())
    self._progressive = ProgressiveMCPRegistry(always_loaded_names=core_names)
    self._full_tools: list[BaseTool] = []
    self._deferred_descriptors: list[MCPToolDescriptor] = []
```

At agent build, call `set_tool_catalog(all_mcp_tools)` with **every** connected MCP `BaseTool` (not just always-loaded).

### 8.2 `abefore_agent`

- Lazy-init `state["mcp_activation"]` if missing
- Preserve `disabled_mcp_servers` init (unchanged)

### 8.3 `awrap_tool_call`

| Tool name | Action |
|-----------|--------|
| `search_mcp_tools` | Parse `query`/`limit`; `search_deferred`; `mark_promoted`; return match list ToolMessage |
| `mcp__*__*` | Run handler; on success (no invalid-tool error), `mark_promoted([tool_name])` |
| other | pass through |

Disabled-server check: if `server in disabled_mcp_servers`, return ToolMessage error before handler (don't promote).

### 8.4 `awrap_model_call`

```python
bound = self._progressive.bound_tools(request.tools, activation)
request = request.override(tools=bound)
return await handler(request)
```

Binding rule: keep all non-MCP tools unchanged; filter only tools matching `^mcp__`. Core MCP tools always pass; deferred pass only if promoted.

**Alternative (simpler filter)**: `bound_tools` receives full tool list; returns `[t for t in tools if not is_mcp(t) or t.name in allowed_mcp_names]`.

### 8.5 Telemetry

Retain `emit_tool_search_queried` on `search_mcp_tools`. Add `emit_mcp_tool_promoted` event (new, optional v1).

---

## 9. `search_mcp_tools` discovery stub

Location: `packages/soothe/src/soothe/mcp/discovery_tools.py`

Same stub pattern as `create_search_tools_tool()` / `create_search_skills_tool()`:

```python
def create_search_mcp_tools_tool() -> StructuredTool:
    """Stub; promotion handled by MCPActivationMiddleware."""
```

Description text:

> Search deferred MCP tools by server name, tool name, or description. Returns matches and promotes them for subsequent model hops. Use exact mangled names (mcp__server__tool) when calling.

Registered in `_builder.py` whenever `mcp_registry` has deferred tools.

**Core tier inclusion**: `search_mcp_tools` is always bound (like `search_tools`). Optionally add to `DEFAULT_CORE_TOOL_NAMES` when MCP registry present — or inject only when MCP servers exist.

---

## 10. Agent build changes

### 10.1 Full catalog registration

Current (broken):

```python
all_tools.extend(registry.always_loaded_tools())  # deferred omitted
```

Target:

```python
all_mcp = registry.all_tools()  # NEW method: flatten _tools dict
all_tools.extend(all_mcp)
# MCPActivationMiddleware.set_tool_catalog(all_mcp) at stack build
```

`MCPRegistry.all_tools()` returns all policy-visible `BaseTool` instances across servers (respecting `tool_filter`, skipping disabled servers).

### 10.2 Middleware stack order

```
SoothePolicy
→ SkillActivationMiddleware
→ MCPActivationMiddleware        # replaces MCPToolSearchMiddleware
→ ToolCallArgsMiddleware
→ ...
→ ProgressiveToolMiddleware      # builtin tools
→ SystemPromptMiddleware         # composes AVAILABLE_* blocks
```

`MCPActivationMiddleware` must sit **before** `SystemPromptMiddleware` (for state init) and implement `awrap_model_call` **after** tools are assembled (middleware order: outer wraps first for model call — verify existing progressive tools order and match).

Current order: SkillActivation → MCPToolSearch → ... → ProgressiveTool → SystemPrompt. MCP activation should mirror ProgressiveTool placement: **before** SystemPrompt, with `awrap_model_call` filtering.

---

## 11. System prompt integration

### 11.1 `_compose_mcp_tools_block` refactor

Migrate from flat `sent_mcp_tool_names` to `mcp_activation`:

```python
activation = state.get("mcp_activation") or ProgressiveMCPRegistry.init_activation_state()
deferred = self._mcp_registry.deferred_tools()
new_entries = self._progressive_mcp_registry.new_for_thread(activation, deferred)
# format_mcp_tools_within_budget(new_entries, ...)
self._progressive_mcp_registry.mark_sent(activation, [d.name for d in new_entries])
state["mcp_activation"] = activation
```

Exclude promoted tools from listing (already callable — same as tools omitting promoted from `<AVAILABLE_TOOLS>`).

### 11.2 Prompt guidance (static tier)

Add to `<TOOL_SELECTION>` or a new `<MCP_TOOL_DISCOVERY>` snippet when MCP servers connected:

```
Deferred MCP tools appear in AVAILABLE_MCP_TOOLS. Use search_mcp_tools(query) to find and
activate them, then call the exact mangled name mcp__<server>__<tool>.
```

---

## 12. Data flows

### Flow 1: Cold start (defer=true server, 50 tools)

1. Daemon: `MCPRegistry.initialize()` fetches 50 tools into `_tools[server]`.
2. Agent build: all 50 `BaseTool` in catalog; 0 bound (none promoted, none always-loaded).
3. Turn 0 prompt: `<AVAILABLE_MCP_TOOLS>` lists up to budget (delta = all 50 first time, truncated).
4. Model calls `search_mcp_tools(query="create issue", limit=5)`.
5. Middleware promotes matches; returns descriptions.
6. Turn 1: `awrap_model_call` binds promoted tools; model can call `mcp__github__create_issue`.
7. Direct invoke without prior search also promotes (parity with `ProgressiveToolMiddleware`).

### Flow 2: Always-loaded server (defer=false, 5 tools)

1. 5 tools in core tier — bound every hop from turn 0.
2. Not listed in `<AVAILABLE_MCP_TOOLS>` (already in tool schemas).
3. `is_essential=True` in budget formatter if ever listed.

### Flow 3: Iteration boundary

1. StrangeLoop executor snapshots `state["mcp_activation"]` → `LoopState.mcp_activation_sent/promoted`.
2. Resume rehydrates before first `abefore_agent`.

### Flow 4: Server disabled mid-thread

1. `disabled_mcp_servers` contains server name.
2. `awrap_model_call` excludes all `mcp__<server>__*` from bound set.
3. `awrap_tool_call` rejects invocations with clear error.

---

## 13. Error handling

| Case | Behavior |
|------|----------|
| MCP registry not initialized | Skip MCP middleware; no MCP tools |
| Server disconnected | Invocation fails via registry; no promotion |
| Invalid tool name | No promotion (mirror `is_invalid_tool_error` check) |
| `search_mcp_tools` empty results | ToolMessage: "No deferred MCP tools matched query=..." |
| Tool on disabled server | ToolMessage error; no promotion |

---

## 14. Testing plan

| Test | Location |
|------|----------|
| `ProgressiveMCPRegistry.partition/search/promote` | `tests/unit/mcp/test_progressive_registry.py` |
| `search_mcp_tools` promotes + message content | `tests/unit/middleware/test_mcp_activation.py` |
| `awrap_model_call` binds core + promoted only | same |
| Direct `mcp__*` invoke promotes | same |
| `_compose_mcp_tools_block` delta + excludes promoted | extend `tests/unit/middleware/test_system_prompt.py` |
| LoopState snapshot round-trip | `tests/unit/core/loop/test_mcp_activation_durability.py` |
| Integration: 50 deferred tools, search → call | `tests/integration/mcp/test_progressive_mcp_tool_surfacing.py` (RFC-412 planned) |

---

## 15. Migration / cleanup

1. **Delete** `middleware/mcp_tool_search.py` → replaced by `mcp_activation.py`.
2. **Migrate** flat LoopState fields to `mcp_activation_*` (or nested `mcp_activation` dict on LoopState).
3. **Update** executor rehydrate in `executor.py`.
4. **Update** RFC-412 §Flow 3 to reflect unified `mcp_activation` state (revision, not new RFC).
5. **Fix** wiki `capabilities/mcp.md` — document actual behavior post-implementation.
6. **Remove** dead `invoked_mcp_tools` dict shape (tool_name → {server, tool, args}) — promotion only needs name set.

---

## 16. Implementation phases

### Phase 1 — Runtime activation (P0, unblocks deferred MCP)

- `ProgressiveMCPRegistry`
- `MCPActivationMiddleware` with `awrap_model_call` + invoke promotion
- `MCPRegistry.all_tools()`
- Agent build: register full catalog
- LoopState + executor migration

### Phase 2 — Discovery tool (P0)

- `search_mcp_tools` stub + middleware handler
- Prompt guidance snippet

### Phase 3 — Polish (P1)

- `emit_mcp_tool_promoted` event
- Disabled-server filtering in `awrap_model_call`
- Integration test with mock MCP server

### Phase 4 — Deferred (P2)

- Intent prefetch from user message (corpus match on tool descriptions)
- Semantic search over MCP tool embeddings
- Per-tool `_meta` alwaysLoad from MCP protocol

---

## 17. Open questions

1. **Should `search_mcp_tools` be in `DEFAULT_CORE_TOOL_NAMES` globally?**  
   Recommendation: inject only when `mcp_registry` has ≥1 deferred tool (avoid orphan tool).

2. **Promote on failed MCP RPC?**  
   Recommendation: no — only promote when ToolMessage is not an invalid-tool / transport error (match builtin tools).

3. **Compaction eviction of `sent`/`promoted`?**  
   Follow skills/tools: `sent` may reset on compaction; `promoted` persists for thread lifetime unless explicit eviction policy added later.

---

## 18. Success criteria

- [ ] Agent with 50 deferred MCP tools: turn-0 binds 0 MCP schemas; prompt listing < `budget_pct` of context.
- [ ] After `search_mcp_tools`, promoted tools appear in `tools=` on next hop.
- [ ] Direct `mcp__*` call without search still works and promotes.
- [ ] `defer: false` tools bound from turn 0 without search.
- [ ] State survives iteration boundary round-trip.
- [ ] `./scripts/verify_finally.sh` passes.
