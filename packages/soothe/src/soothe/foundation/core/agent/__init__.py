"""CoreAgent -- Layer 1 runtime (RFC-0023).

Self-contained module wrapping CompiledStateGraph with typed protocol properties.
Pure execution runtime - NO goal infrastructure (Layer 2/3 responsibility).

Architecture:

┌─────────────────────────────────────────────────────────────────────┐
│  Soothe CoreAgent (Layer 1)                                         │
│  ┌─────────────────────────────────────────────────────────────┐    │
│  │  Typed Properties: context, memory, planner, policy         │    │
│  │  Execution Interface: astream(input, config)                │    │
│  │  Layer 2 Contract: thread_id, workspace, execution hints    │    │
│  └─────────────────────────────────────────────────────────────┘    │
│                              ↓                                      │
│  ┌─────────────────────────────────────────────────────────────┐    │
│  │  Soothe Middleware Stack:                                 │    │
│  │  1. SoothePolicyMiddleware - safety enforcement             │    │
│  │  2. SystemPromptMiddleware - dynamic prompts                │    │
│  │  3. WorkspaceContextMiddleware - thread workspace           │    │
│  │  4. SubagentContextMiddleware - context briefing            │    │
│  └─────────────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────────┐
│  LangGraph CompiledStateGraph                                       │
│  - State graph runtime                                              │
│  - Built-in middleware: TodoList, Filesystem, SubAgent, etc.        │
│  - Tool parallelism via asyncio.gather                              │
│  - BackendProtocol for file/execution operations                    │
└─────────────────────────────────────────────────────────────────────┘

Layer 2 Contract (config.configurable):
    - thread_id: Thread identifier for persistence
    - workspace: Thread-specific workspace path (RFC-103)
    - soothe_step_subagent: Suggested subagent (advisory)
    - soothe_step_expected_output: Expected result (advisory)
"""

from soothe.foundation.core.agent._builder import AgentBuilder, create_soothe_agent
from soothe.foundation.core.agent._core import CodingCoreAgent, CoreAgent

__all__ = [
    "AgentBuilder",
    "CodingCoreAgent",
    "CoreAgent",
    "create_soothe_agent",
]
