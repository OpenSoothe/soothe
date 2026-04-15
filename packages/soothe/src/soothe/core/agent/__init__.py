"""CoreAgent -- Layer 1 runtime (RFC-0023).

Self-contained module wrapping CompiledStateGraph with typed protocol properties.
Pure execution runtime - NO goal infrastructure (Layer 2/3 responsibility).

This module defines the clear boundary between Soothe and deepagents:

┌─────────────────────────────────────────────────────────────────────┐
│  Soothe CoreAgent (Layer 1)                                         │
│  ┌─────────────────────────────────────────────────────────────┐    │
│  │  Typed Properties: context, memory, planner, policy         │    │
│  │  Execution Interface: astream(input, config)                │    │
│  │  Layer 2 Contract: thread_id, workspace, execution hints    │    │
│  └─────────────────────────────────────────────────────────────┘    │
│                              ↓                                      │
│  ┌─────────────────────────────────────────────────────────────┐    │
│  │  Soothe Middleware Stack (5 middlewares):                   │    │
│  │  1. SoothePolicyMiddleware - safety enforcement             │    │
│  │  2. SystemPromptOptimizationMiddleware - dynamic prompts    │    │
│  │  3. ExecutionHintsMiddleware - Layer 2 → Layer 1 hints      │    │
│  │  4. WorkspaceContextMiddleware - thread workspace           │    │
│  │  5. SubagentContextMiddleware - context briefing            │    │
│  └─────────────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────────┐
│  deepagents (create_deep_agent)                                     │
│  - CompiledStateGraph runtime                                       │
│  - Built-in middleware: TodoList, Filesystem, SubAgent, etc.       │
│  - Tool parallelism via asyncio.gather                              │
│  - BackendProtocol for file/execution operations                    │
└─────────────────────────────────────────────────────────────────────┘

Layer 2 Contract (config.configurable):
    - thread_id: Thread identifier for persistence
    - workspace: Thread-specific workspace path (RFC-103)
    - soothe_step_tools: Suggested tools (advisory)
    - soothe_step_subagent: Suggested subagent (advisory)
    - soothe_step_expected_output: Expected result (advisory)
"""

from soothe.core.agent._builder import AgentBuilder, create_soothe_agent
from soothe.core.agent._core import CoreAgent

__all__ = [
    "AgentBuilder",
    "CoreAgent",
    "create_soothe_agent",
]
