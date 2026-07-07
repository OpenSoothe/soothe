"""AgentLoop Multi-Thread Integration Summary (RFC-608 Completion).

This document outlines the key changes needed to integrate RFC-608 multi-thread
lifecycle into agent_loop.py run_with_progress() method.

**Key Integration Points**:

1. **Loop Identity Change**: 
   - Change from `state_manager = AgentLoopStateManager(thread_id)` 
   - To: `state_manager = AgentLoopStateManager(loop_id or None)`
   - Generate or load loop by loop_id, not thread_id

2. **Thread Switching Policy Integration**:
   - Before goal execution: Evaluate ThreadSwitchPolicy
   - If triggered: Execute thread switch (create new thread, auto /recall)
   - Update checkpoint with new thread

3. **Goal-Thread Relevance Analysis**:
   - Call analyze_goal_thread_relevance() before goal start
   - If hindering detected: Trigger thread switch
   - LLM determines goal independence, domain mismatch, pollution

4. **Thread Health Monitoring**:
   - After goal completion: Update thread_health_metrics
   - Track message history tokens, failures, checkpoint errors

5. **Context Injection**:
   - Previous goal final_report (same-thread continuation)
   - Auto /recall results (if thread switched)

**Modified Flow**:

```
async def run_with_progress(goal, thread_id, loop_id=None):
    # RFC-608: Loop-scoped state manager
    state_manager = AgentLoopStateManager(loop_id)
    
    checkpoint = state_manager.load()
    
    # RFC-608: Handle multi-thread lifecycle
    if checkpoint and checkpoint.status == "ready_for_next_goal":
        # Evaluate thread switching policy
        should_switch, reason = policy_manager.evaluate(checkpoint, goal)
        
        if should_switch:
            # Execute thread switch
            new_thread_id = create_new_thread()
            state_manager.execute_thread_switch(new_thread_id)
            
            # Auto /recall from previous threads
            recall_context = state_manager.auto_recall_on_thread_switch(goal, policy)
            
        # Create new goal record
        goal_record = state_manager.start_new_goal(goal)
        checkpoint.goal_history.append(goal_record)
        checkpoint.current_goal_index = len(checkpoint.goal_history) - 1
        
        # Inject context
        plan_excerpts = state_manager.inject_previous_goal_context()
        if recall_context:
            plan_excerpts.extend(recall_context)
            
    elif not checkpoint:
        # Initialize new loop
        checkpoint = state_manager.initialize(thread_id)
        goal_record = state_manager.start_new_goal(goal)
        checkpoint.goal_history.append(goal_record)
        checkpoint.current_goal_index = 0
        
    # Main Plan → Execute loop
    while goal_record.iteration < goal_record.max_iterations:
        # ... existing logic
        # Pass goal_record to state_manager.record_iteration()
        
    # Goal completed
    final_report = await generate_final_report()
    state_manager.finalize_goal(goal_record, final_report)
    
    # Update thread health metrics
    update_thread_health_metrics(checkpoint)
```

**Implementation Strategy**:

Due to agent_loop.py complexity (540 lines), we'll:
1. Create a new method `_handle_loop_lifecycle()` to encapsulate thread switching logic
2. Modify `run_with_progress()` to call this method
3. Update iteration recording to use goal_record instead of checkpoint
4. Add thread health monitoring hooks

This approach minimizes disruption to existing execution flow while enabling multi-thread spanning.
"""