# IG-443: Checkpoint Fork In-House Copy + Sole-Child Optimization

**Status**: Complete
**RFC**: [RFC-223 (revised 2026-05-28)](../specs/RFC-223-thread-inheritance-checkpoint-forking.md)
**Created**: 2026-05-28

---

## Purpose

RFC-223 specified checkpoint inheritance for AgentLoop step execution via
LangGraph's ``BaseCheckpointSaver.acopy_thread`` API. None of the concrete
savers in the current LangGraph release (``InMemorySaver``,
``AsyncSqliteSaver``, ``AsyncPostgresSaver`` and their shallow variants)
implement ``acopy_thread`` — they all inherit the base class's
``raise NotImplementedError``. The result was that every parallel step
that tried to fork its predecessor's checkpoint logged a full warning
traceback and silently fell back to using the source thread directly.

This IG closes that gap by implementing the copy ourselves on top of the
public ``alist`` + ``aput`` + ``aput_writes`` surface that every saver
does support, and adds a sole-child optimization that skips the copy
altogether when only one step depends on a given predecessor.

---

## Scope

### In Scope

1. ``copy_thread_via_public_api`` helper that iterates source thread
   checkpoints, rewrites ``configurable.thread_id``, and replays them on
   the target thread.
2. ``ThreadForkManager.fork_checkpoint`` switched to use the helper.
3. Sole-child optimization: ``select_fork_source`` returns
   ``(source, should_fork)``; when ``should_fork=False``, the manager
   reuses the predecessor's thread directly with no copy.
4. Sibling fork preserved: when a predecessor has ≥2 dependents, each
   child gets its own fork copy so their histories don't pollute each
   other.
5. Tests for the helper and the optimization.
6. Updated downstream tests that were written under the
   "every-singleton-forks" assumption.

### Out of Scope

- Thread cleanup / pruning of forked checkpoints once the goal completes
  (RFC-223 §"Risks and Mitigations" lists this; out of scope for v1).
- Replacing ``aput_writes``-based pending-write copy with a more
  efficient bulk-copy primitive (only matters when forks land between
  step writes, which is rare).

---

## Files Changed

### New

| Path | Purpose |
|------|---------|
| ``packages/soothe/src/soothe/core/loop/engine/checkpoint_copy.py`` | ``copy_thread_via_public_api`` helper |
| ``packages/soothe/tests/unit/core/loop/engine/test_checkpoint_copy.py`` | Helper unit tests against ``InMemorySaver`` |

### Modified

| Path | Changes |
|------|---------|
| ``packages/soothe/src/soothe/core/loop/engine/thread_fork_manager.py`` | ``select_fork_source`` returns ``(source, should_fork)`` with sole-child branch; ``_count_dependents`` helper; ``fork_checkpoint`` calls ``copy_thread_via_public_api``; ``prepare_thread_for_step`` skips copy when ``should_fork=False`` |
| ``packages/soothe/tests/unit/core/loop/engine/test_thread_fork_manager.py`` | Updated for new tuple return shape and sole-child / siblings split |
| ``packages/soothe/tests/unit/core/loop/engine/test_executor_branch_predecessor.py`` | ``test_singleton_sole_child_reuses_predecessor_thread`` (renamed from the old "forks from predecessor" test); ``test_fork_copies_main_thread_into_step_namespace`` patches the helper |
| ``packages/soothe/tests/unit/core/loop/engine/test_executor_hints.py`` | ``test_executor_thread_fork_creates_isolated_thread`` patches the helper instead of asserting on saver's ``acopy_thread`` |
| ``docs/specs/RFC-223-thread-inheritance-checkpoint-forking.md`` | Revised strategy table + changelog entry |

---

## Verification

```
./scripts/verify_finally.sh
```

After this IG: ``soothe`` package goes from 1962 to 1970 unit tests passing
(net +8 after rewrites). All packages clean.

Specific test files covering this work:

```
packages/soothe/tests/unit/core/loop/engine/test_checkpoint_copy.py
packages/soothe/tests/unit/core/loop/engine/test_thread_fork_manager.py
packages/soothe/tests/unit/core/loop/engine/test_executor_branch_predecessor.py
packages/soothe/tests/unit/core/loop/engine/test_executor_hints.py
```

---

## Notes

- The helper uses ``alist`` to materialize the full checkpoint list before
  re-puting them. ``alist`` yields most-recent-first; the helper reverses
  to oldest-first so parent_config links remain consistent during replay.
- ``new_versions`` for ``aput`` is reconstructed as an empty mapping. The
  saved checkpoint already encodes complete channel versions;
  ``new_versions`` represents the **delta** for an incremental write,
  which is empty when re-puting a complete pre-existing checkpoint.
- Pending writes (mid-step ``aput_writes`` entries on a checkpoint) are
  replayed via ``aput_writes``. In practice forks happen at step
  boundaries with no pending writes, but copying them anyway is the
  conservative correctness choice.

---

## Changelog

### 2026-05-28
- IG created and implementation completed in one pass
- Sole-child optimization implemented + tested
- In-house ``copy_thread_via_public_api`` implemented + tested
- RFC-223 revised
