# Subagents Architecture

**Subagents** are specialized autonomous agents that perform multi-step, stateful workflows. They extend Soothe's capabilities beyond simple tool invocations, enabling complex operations like filesystem exploration, structured planning, and deep research — tasks that require multiple LLM calls, tool invocations, and iterative refinement.

## Subagent vs Tool: The Capability Spectrum

The distinction is architectural, not just functional. Tools are stateless, single-shot, and immediate. Subagents are stateful, multi-step, and long-running. The key differentiator is **orchestration**: a subagent uses the LLM to decide *which* tool to call *next*, based on what it has learned so far. A tool simply executes.

| Dimension | Tool | Subagent |
|-----------|------|----------|
| LLM calls | Zero or one | Multiple, orchestrated |
| State | Stateless | Stateful (accumulates findings) |
| Duration | Milliseconds to seconds | Seconds to minutes |
| Dependencies | None | May call tools or other subagents |
| Output | Direct result | Structured report |

This spectrum matters for cost and reliability: subagents consume more tokens but handle ambiguity and adaptive search that no single tool call can. Use a subagent when the *path* to the answer is unknown and must be discovered iteratively.

## Architecture Pattern

All subagents follow a consistent pattern (RFC-600/601): a `@plugin` + `@subagent` decorated factory function that returns a compiled LangGraph `StateGraph`. The graph has a typed state schema, LLM-driven nodes, tool nodes, conditional edges for flow control, and a structured output schema.

The critical contract: **state must include `messages: Annotated[list, add_messages]`** and the final node must return a single `AIMessage`. This is the `CompiledSubAgent` contract that allows subagents to be invoked by the main agent's `task` tool.

→ Source: `packages/soothe/src/soothe/subagents/`

## Built-in Subagents

The core `soothe` package ships five built-in subagents: **planner**, **tacitus**, **browser_use**, **skillify**, and **veritas**. Each is registered via the `@plugin` + `@subagent` decorator pattern (except veritas, which is a direct structured-output call invoked by `AutoClarificationPolicy`).

### Planner (RFC-618): Structured Planning with Iterative Refinement

Planner is a multi-round planning subagent: it iteratively refines a markdown execution plan until the model declares it complete, then returns a single structured report. The design separates plan design from execution, giving the main agent a stable blueprint to follow.

**Key design decisions:**
- **Agentic refinement loop** — planning runs multiple refinement rounds, each producing a progressively refined markdown plan, until the model declares "done."
- **Think-role model** — the resolver always passes the router's `think` role, ensuring the strongest reasoning model is used for plan design.
- **Bounded cost** — explicit cap on `max_plan_rounds` prevents runaway refinement loops.
- **Registered as `name="planner"`** — the subagent directory is `plan/` but the plugin and subagent name is `planner`. Triggers include `planner`, `decompose`, `roadmap`, `break down`.

### Tacitus (RFC-619): Public-Domain Research

Tacitus is the research subagent for public-domain sources: web search, Wikipedia, academic papers, and URL crawling. Its architecture is analyze → generate_queries → gather → summarize → reflect → (iterate or synthesize).

**Key design decisions:**
- **Public-only boundary** — tacitus deliberately restricts itself to public information sources. This is a trust boundary: research results don't access private data, making the subagent safe for autonomous use.
- **Semantic routing** — a `PublicSemanticRouter` uses sentence-transformer embeddings to select which sources to query based on semantic similarity between the query and each capability's description. This is smarter than keyword matching — it routes "climate change effects" to academic search even without the word "paper."
- **Fast-paths** — URL regex patterns trigger `url_crawl` inclusion; arXiv ID patterns boost `academic_search`. These heuristics shortcut the semantic router for obvious cases.
- **Domain profiles** — `public` (all sources), `web`, `academic` — restricts the source set for focused research.

### Veritas (RFC-622): Intent-Grounded Clarification

Veritas is unique — it's not a general-purpose subagent but a **single structured-output LLM call** invoked by `AutoClarificationPolicy` when the StrangeLoop pauses on an `ask_user` interrupt in autonomous mode. It produces a best-effort answer from the goal's first-principles context.

If veritas cannot answer with sufficient confidence, it sets `defer=True` and the loop transitions the goal to `awaiting_clarification` for out-of-band human resolution. This is the autonomous-mode safety valve: the system attempts self-resolution before blocking on human input.

### Skillify: Semantic Skill Retrieval

Skillify is the skill warehouse subagent — it indexes and retrieves skills using semantic search. It provides a `SkillRetriever` that builds an incremental, mtime-cached index of user skills, enabling the agent to discover relevant skills by semantic similarity rather than keyword matching.

### Browser Use (Opt-in)

**browser_use**: Browser automation (navigate, click, fill, extract, screenshot). Ships with base `soothe` dependencies but `on_load` verifies runtime deps.

## Model Role Resolution

Subagents use specific model roles, not the main agent's model. This is a cost optimization:

| Subagent | Model Role | Rationale |
|----------|------------|-----------|
| planner | `think` | Plan design needs the strongest reasoning model |
| tacitus | `fast` | Query generation and summarization are fast-model tasks |
| browser_use | `default` | Browser step planning uses the default model |
| skillify | `default` | Skill retrieval uses the default model |

The planner subagent's primary model always uses the router's `think` role — planning quality directly determines execution quality. Note that `subagents.<name>.model` config overrides are **ignored** for built-in subagents; the role is fixed by design.

## Workspace Isolation

Subagents inherit workspace boundaries from the invoking context. The resolver provides a static workspace (daemon workspace) as a fallback, but thread-level workspace is injected at runtime via `state.workspace` (IG-328). This means subagent operations are always scoped — a subagent invoked in thread A cannot access thread B's workspace.

## Extension Pattern

Creating a custom subagent follows the module self-containment pattern (IG-047):

```
subagents/<name>/
├── __init__.py        # Plugin definition + public API
├── events.py          # Wire events + register_event() calls
├── implementation.py  # Factory function
├── schemas.py         # State + output schemas
└── engine.py          # LangGraph StateGraph (if complex)
```

The minimal plugin definition:

```python
from soothe_sdk.plugin import plugin, subagent

@plugin(name="my-agent", version="1.0.0", trust_level="standard")
class MyAgentPlugin:
    @subagent(name="my_agent", description="My custom agent",
              triggers=["keyword1"])  # Optional: auto-routing keywords
    async def create_agent(self, model, config, context):
        return create_my_agent(model, config, context)
```

The factory function builds a `StateGraph`, adds nodes and conditional edges, and returns `graph.compile()`. State must include `messages: Annotated[list, add_messages]`; output should be a Pydantic model (not a raw dict) for type safety.

## Integration Points

- **Task tool**: Subagents are invoked via the `task` tool, which resolves the subagent via `resolve_subagents()` from PluginRegistry, invokes the compiled runnable, and returns structured results.
- **Policy**: All subagent operations pass through PolicyProtocol (`subagent:invoke:<name>`).
- **Events**: Each subagent emits lifecycle events in the `soothe.subagent.<name>.*` namespace — `started`, `iteration`/`collection_round`, `completed`. These provide observability for long-running workflows.

## Gotchas

- **CompiledSubAgent contract**: forgetting `messages: Annotated[list, add_messages]` in state or not returning a single `AIMessage` from the final node causes runtime errors. This is the most common subagent bug.
- **Event registration**: events must be imported in `__init__.py` for side-effect registration. Missing this import means events silently don't fire.
- **Workspace at runtime**: the static `work_dir` from context is a fallback only — always use `state.workspace` for thread-correct behavior.
- **Bounded costs**: always set iteration caps. Unbounded subagent loops consume tokens indefinitely — the built-in subagents all have explicit caps for this reason.

## Related RFCs

| RFC | Title |
|-----|-------|
| [RFC-600](../../specs/RFC-600-plugin-extension-system.md) | Plugin Extension System |
| [RFC-601](../../specs/RFC-601-built-in-agents.md) | Built-in Plugin Agents |
| [RFC-618](../../specs/RFC-618-plan-subagent-delegation.md) | Plan Subagent |
| [RFC-619](../../specs/RFC-619-tacitus-subagent.md) | Tacitus Subagent |
| [RFC-622](../../specs/RFC-622-coreagent-clarification-relay.md) | Veritas Auto-Clarification |

---

**Previous**: [Capabilities Index](index.md) | **Next**: [Tools System](tools.md)
