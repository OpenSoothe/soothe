# IG-764 — Step↔Thread Surfacing Consolidation
Status: approved, implement now.
Motivation: Fix alignment gaps between StrangeLoop steps and CoreAgent threads; retire dead anchor/branch checkpoint machinery and the loop tree/prune surface; collapse the loop registry to a single invariant; own the thread-id grammar in one place; carry interrupt-resume identity in a single ResumeTicket channel.

Direction: Consolidate on the Context Engine (CE) spine as the single source of truth for loop/thread mapping. Drop the parallel anchor/branch tables (checkpoint_anchors, failed_branches) — they were never written in production.

Invariants:
1. Main thread id == loop_id (the only registry invariant).
2. CE is the working registry: StepExecution.thread_id, goal_records.thread_id, ledger execute_step rows carry thread_id + iteration.
3. Thread ids are random opaque (execute step = {main}__{hex5}); no deterministic step-id encoding.
4. Checkpoints are reachable via shared checkpointer, not indexed by a stored checkpoint_id.

Work areas:
A. Retire anchor/branch machinery (manager + 3 backends + DDL + anchor_manager.py + record_progress capture). [THIS TASK]
B. Retire RPC/CLI surface (loop_tree/loop_prune RPCs + CLI commands). [separate worker]
C. Collapse loop registry to main-thread==loop_id invariant (loop_dispatcher, docstrings). [separate worker]
D. Thread-id grammar ownership in orchestrator/checkpoint.py + thread_kind() classifier. [separate worker]
E. ResumeTicket single channel replacing resume_thread_id/resume_step_id/resume_step_description. [separate worker]
