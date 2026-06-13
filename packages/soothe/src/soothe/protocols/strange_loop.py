"""StrangeLoopProtocol - Layer 2 Plan-Execute orchestration interface.

StrangeLoop (alias: Sloop) executes single goals through iterative refinement,
delegating step execution to CoreAgentProtocol. Loop knows CoreAgent, CoreAgent
doesn't know Loop.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:
    from soothe.config import SootheConfig
    from soothe.foundation.loop.state.schemas import LoopState, PlanResult
    from soothe.protocols.core_agent import CoreAgentProtocol


@runtime_checkable
class StrangeLoopProtocol(Protocol):
    """Layer 2 StrangeLoop interface - Plan-Execute orchestration.

    StrangeLoop executes single goals through iterative refinement:
    - Plan: LLM reasoning with goal-directed evaluation
    - Execute: Step execution via CoreAgentProtocol
    - Judge: Progress assessment toward goal

    This protocol enables alternative StrangeLoop implementations while
    maintaining CoreAgent isolation (Loop knows Core, Core doesn't know Loop).

    Key responsibilities:
    - Iterative Plan-Execute loop (max ~8 iterations)
    - Evidence accumulation from execution
    - Goal-directed judgment (done/continue/replan)
    - Thread isolation for subagent steps
    """

    async def run_iteration(
        self,
        state: LoopState,
    ) -> PlanResult:
        """Execute one Plan-Execute iteration.

        Args:
            state: LoopState with goal, iteration count, plan context,
                working memory, and thread metadata.

        Returns:
            PlanResult with status (continue/replan/done), evidence,
            confidence, and optional next steps (AgentDecision).
        """
        ...

    async def run_with_progress(
        self,
        goal_text: str,
        thread_id: str,
        **kwargs: Any,
    ) -> PlanResult | None:
        """Run full StrangeLoop for a goal with progress tracking.

        Args:
            goal_text: Goal description to execute
            thread_id: Thread identifier for persistence
            **kwargs: Additional execution context

        Returns:
            Final PlanResult if goal executed, None if no goal ready.
        """
        ...

    @classmethod
    def create(
        cls,
        config: SootheConfig,
        core_agent: CoreAgentProtocol,
    ) -> StrangeLoopProtocol:
        """Factory method requiring CoreAgentProtocol dependency.

        Args:
            config: SootheConfig with loop settings
            core_agent: CoreAgentProtocol instance for execution

        Returns:
            StrangeLoopProtocol instance ready for iteration.
        """
        ...
