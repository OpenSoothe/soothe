# Checkpoint Tree Integration & Testing

> Implementation guide for integration testing across all checkpoint tree RFCs.
>
> **Phases**: IG-239 (Persistence) + IG-240 (Checkpoint Tree) + IG-241 (Loop UX) + IG-242 (Event Replay)
> **RFCs**: RFC-409, RFC-611, RFC-503, RFC-504, RFC-411
> **Language**: Python 3.11+

---

## 1. Overview

Comprehensive integration testing for complete checkpoint tree feature. Validate end-to-end workflows across all phases: persistence backend, checkpoint synchronization, loop UX, and event replay.

## 2. Integration Test Scenarios

### 2.1 Scenario 1: Complete Smart Retry Workflow

**Test**: Fresh execution → failure → branch creation → analysis → retry → success

```python
@pytest.mark.integration
async def test_complete_smart_retry_workflow():
    """Test complete smart retry cycle across all components."""
    
    # 1. Start loop
    loop_id = "test_retry_loop"
    soothe = SootheRunner(loop_id)
    
    # 2. Execute query (will trigger timeout failure)
    with pytest.raises(TimeoutError):
        await soothe.run("analyze large file without streaming")
    
    # 3. Verify failed branch created
    checkpoint = await persistence_manager.load_agentloop_checkpoint(loop_id)
    assert len(checkpoint.checkpoint_tree_ref.failed_branches) == 1
    
    branch = list(checkpoint.checkpoint_tree_ref.failed_branches.values())[0]
    assert branch.failure_reason == "Timeout"
    
    # 4. Verify failure analysis
    assert branch.analyzed_at is not None
    assert len(branch.avoid_patterns) > 0
    assert len(branch.suggested_adjustments) > 0
    
    # 5. Verify smart retry executed
    goals = checkpoint.goal_history
    retry_goal = goals[-1]  # Last goal is retry
    assert retry_goal.status == "completed"
    
    # 6. Verify checkpoint tree
    anchors = await persistence_manager.get_checkpoint_anchors_for_range(loop_id, 0, 10)
    assert len(anchors) >= 4  # iteration_0_start, iteration_0_end, retry_start, retry_end
```

---

### 2.2 Scenario 2: Loop Detachment & Reattachment

**Test**: Detach loop → execution continues → reattach → history reconstruction

```python
@pytest.mark.integration
async def test_loop_detachment_reattachment_workflow():
    """Test detachment and reattachment with history replay."""
    
    # 1. Create loop and execute goals
    loop_id = "test_detach_loop"
    soothe = SootheRunner(loop_id)
    
    await soothe.run("goal 1")
    await soothe.run("goal 2")
    
    # 2. Detach loop (client disconnects)
    client_session = MockClientSession(loop_id)
    await handle_loop_detach(loop_id, client_session)
    
    # 3. Verify loop continues running
    checkpoint = await persistence_manager.load_agentloop_checkpoint(loop_id)
    assert checkpoint.status == "running"  # Loop still active
    
    # 4. Execute more goals while detached
    await soothe.run("goal 3")  # Detached execution
    
    # 5. Reattach client
    await handle_loop_reattach(loop_id, client_session)
    
    # 6. Verify history replay received
    assert client_session.received_events["history_replay"]
    
    # 7. Verify complete history (goals 1-3)
    replay_events = client_session.received_events["history_replay"]["events"]
    goal_events = [e for e in replay_events if e["type"] == GOAL_CREATED]
    assert len(goal_events) == 3  # All goals reconstructed
```

---

### 2.3 Scenario 3: Thread Switch with Checkpoint Anchors

**Test**: Thread switch → checkpoint anchors updated → cross-reference maintained

```python
@pytest.mark.integration
async def test_thread_switch_checkpoint_anchor_workflow():
    """Test thread switch preserves checkpoint anchors."""
    
    # 1. Create loop with thread switch policy
    loop_id = "test_switch_loop"
    soothe = SootheRunner(loop_id)
    
    # 2. Execute until thread switch triggered
    await soothe.run("goal that triggers message history threshold")
    
    # 3. Verify thread switch
    checkpoint = await persistence_manager.load_agentloop_checkpoint(loop_id)
    assert len(checkpoint.thread_ids) >= 2  # At least 2 threads
    
    # 4. Verify checkpoint anchors cross-reference
    anchors = await persistence_manager.get_checkpoint_anchors_for_range(loop_id, 0, 10)
    
    thread_checkpoints = {}
    for anchor in anchors:
        if anchor["thread_id"] not in thread_checkpoints:
            thread_checkpoints[anchor["thread_id"]] = []
        thread_checkpoints[anchor["thread_id"]].append(anchor["checkpoint_id"])
    
    # 5. Verify each thread has anchors
    for thread_id in checkpoint.thread_ids:
        assert thread_id in thread_checkpoints
        assert len(thread_checkpoints[thread_id]) > 0
    
    # 6. Verify main_line_checkpoints updated
    main_line = checkpoint.checkpoint_tree_ref.main_line_checkpoints
    assert len(main_line) > 0
    
    # 7. Verify cross-reference: main_line checkpoint_ids exist in anchors
    for iteration, checkpoint_id in main_line.items():
        matching_anchor = [a for a in anchors if a["checkpoint_id"] == checkpoint_id]
        assert len(matching_anchor) > 0
```

---

### 2.4 Scenario 4: CLI Loop Management Commands

**Test**: Loop list/describe/tree/prune commands

```python
@pytest.mark.integration
async def test_cli_loop_management_commands():
    """Test loop CLI commands."""
    
    # 1. Create multiple loops
    loop_1 = await create_loop_with_goals(3)
    loop_2 = await create_loop_with_goals(5)
    loop_3 = await create_loop_with_goals(2)
    
    # 2. Test `soothe loop list`
    loops = await list_loops(status="ready_for_next_goal")
    assert len(loops) >= 3
    
    # 3. Test `soothe loop describe`
    loop_details = await describe_loop(loop_1.loop_id, verbose=True)
    assert loop_details["loop_id"] == loop_1.loop_id
    assert len(loop_details["checkpoint_tree"]["failed_branches"]) >= 0
    
    # 4. Test `soothe loop tree` (ASCII format)
    tree_ascii = await visualize_loop_tree(loop_1.loop_id, format="ascii")
    assert "Main Execution Line:" in tree_ascii
    assert "iteration 0" in tree_ascii
    
    # 5. Test `soothe loop tree` (JSON format)
    tree_json = await visualize_loop_tree(loop_1.loop_id, format="json")
    assert "main_line" in tree_json
    assert "failed_branches" in tree_json
    
    # 6. Test `soothe loop prune`
    pruned_count = await prune_loop_branches(loop_1.loop_id, retention_days=30)
    assert pruned_count >= 0
    
    # 7. Test `soothe loop delete`
    await delete_loop(loop_3.loop_id)
    assert not Path(SOOTHE_HOME / "data/loops" / loop_3.loop_id).exists()
```

---

## 3. End-to-End Test Suite

### 3.1 Full User Journey Test

**Test**: Complete user journey from query → detachment → reattachment → resume

```python
@pytest.mark.e2e
async def test_complete_user_journey():
    """Test complete user journey across all features."""
    
    # Phase 1: Initial execution
    # Phase 2: Smart retry on failure
    # Phase 3: Loop detachment
    # Phase 4: History reconstruction on reattachment
    # Phase 5: Resume execution
    
    # ... full workflow implementation
```

---

## 4. Performance Benchmarks

### 4.1 Checkpoint Anchor Performance

```python
@pytest.mark.performance
async def test_checkpoint_anchor_performance():
    """Benchmark checkpoint anchor save/load performance."""
    
    import time
    
    # Benchmark: save 100 anchors
    start = time.time()
    for i in range(100):
        await save_checkpoint_anchor(loop_id, iteration=i, ...)
    save_time = time.time() - start
    
    # Benchmark: load 100 anchors
    start = time.time()
    anchors = await get_checkpoint_anchors_for_range(loop_id, 0, 100)
    load_time = time.time() - start
    
    # Performance criteria
    assert save_time < 5.0  # 100 anchors in <5s
    assert load_time < 1.0  # Load in <1s
```

---

## 5. Verification Procedure

```bash
# Run integration tests
pytest tests/integration/checkpoint_tree/

# Run E2E tests
pytest tests/e2e/checkpoint_tree/

# Run performance benchmarks
pytest tests/performance/checkpoint_tree/

# Manual verification
soothe doctor --check-all
soothe loop list
soothe loop tree test_loop --format ascii
```

---

## 6. Test Coverage Requirements

| Component | Coverage Target | Test Type |
|-----------|----------------|-----------|
| Persistence backend | 90% | Unit + Integration |
| Checkpoint anchors | 90% | Integration |
| Failed branches | 90% | Integration |
| Smart retry | 85% | E2E |
| Event replay | 85% | E2E |
| CLI commands | 80% | Integration |
| Detachment/reattachment | 80% | E2E |

---

## 7. Files to Create

- `tests/integration/checkpoint_tree/test_smart_retry_workflow.py`
- `tests/integration/checkpoint_tree/test_detachment_reattachment.py`
- `tests/integration/checkpoint_tree/test_thread_switch_anchors.py`
- `tests/integration/checkpoint_tree/test_cli_commands.py`
- `tests/e2e/checkpoint_tree/test_complete_user_journey.py`
- `tests/performance/checkpoint_tree/test_anchor_performance.py`

---

## 8. Verification Checklist

✅ Phase 1 (Persistence Backend): SQLite schema, persistence manager
✅ Phase 2 (Checkpoint Tree): Anchors, branches, smart retry
✅ Phase 3 (Loop UX): CLI commands, daemon APIs, TUI refactoring
✅ Phase 4 (Event Replay): Reconstruction, enrichment, BranchCard
✅ Phase 5 (Integration): End-to-end workflows, performance benchmarks

---

**End of Phase 5 Implementation Guide (IG-243)**

