# Daemon Event Forwarding Matrix

This matrix describes the current daemon-side forwarding contract from
`SootheRunner.astream()` to client transports.

Base transport rule:

- `QueryEngine` forwards every chunk emitted by the runner as `{type:"event", mode, data}`.
- Suppression primarily happens upstream in runner/AgentLoop emission paths.

## Matrix (event_type -> source -> forwarded? -> suppression reason)

| event_type | source | forwarded? | suppression reason |
| --- | --- | --- | --- |
| `soothe.cognition.agent_loop.started` | `_runner_agentic.py::_run_agentic_loop` (`AgenticLoopStartedEvent`) | Yes | N/A |
| `iteration_started` (raw AgentLoop internal) | `agent_loop.py::run_with_progress` -> `_runner_agentic.py` branch | No | Internal debug-only; runner logs only, does not `yield` |
| `plan_decision` (raw AgentLoop internal) | `agent_loop.py::run_with_progress` -> `_runner_agentic.py` branch | No | Internal debug-only; runner logs only, does not `yield` |
| `soothe.cognition.agent_loop.step.started` | `_runner_agentic.py` maps `step_started` -> `AgenticStepStartedEvent` | Yes | N/A |
| `soothe.cognition.agent_loop.step.completed` | `_runner_agentic.py` maps `step_completed` -> `AgenticStepCompletedEvent` | Yes | N/A |
| `stream_event` carrying `ToolMessage` | `agent_loop.py` emits `stream_event`; `_runner_agentic.py::_forward_messages_chunk_for_tool_ui` | Yes | N/A |
| `stream_event` carrying AI tool-invocation metadata (`tool_calls` / `tool_call_chunks`) | Same as above | Yes | N/A |
| `stream_event` carrying plain execute-phase assistant prose | Same as above | No | IG-304 daemon-side suppression: tool-only forwarding for `stream_event` |
| `soothe.output.execution.streaming` | Legacy RFC-614 event name (not emitted in current agentic path) | No | Emission path removed by IG-304 contract; execute text no longer wrapped as output events |
| `soothe.output.goal_completion.streaming` | `_runner_agentic.py` maps `goal_completion_stream` via `_wrap_streaming_output(...)` | Yes (when `output_streaming.enabled=true`) | Suppressed only if global streaming is disabled |
| `soothe.cognition.agent_loop.reasoned` | `_runner_agentic.py` maps `plan` -> `LoopAgentReasonEvent` | Conditional Yes | Suppressed when `status=="done"` and `next_action=="Goal achieved successfully"` |
| `iteration_completed` (raw AgentLoop internal) | `agent_loop.py::run_with_progress` -> `_runner_agentic.py` branch | No | Internal debug-only; runner logs only, does not `yield` |
| `fatal_error` (raw AgentLoop internal) | `agent_loop.py::run_with_progress` can emit `fatal_error`; `_runner_agentic.py` has no handling branch | No | Dropped due to missing forward mapping in runner |
| `soothe.output.goal_completion.responded` | `_runner_agentic.py` in `completed` branch (conditional final stdout) | Conditional Yes | Not emitted when `final_stdout` is empty / conditions not met |
| `soothe.cognition.agent_loop.completed` | `_runner_agentic.py` in `completed` branch (`AgenticLoopCompletedEvent`) | Yes | N/A |
| `soothe.output.chitchat.responded` | `_runner_phases.py::_run_chitchat` (`ChitchatResponseEvent`) | Yes | N/A |
| `soothe.output.quiz.responded` | `_runner_phases.py::_run_quiz` (`QuizResponseEvent`) | Yes | N/A |
| `soothe.output.autonomous.goal_completion.reported` | `_runner_autonomous.py` (`AutonomousGoalCompletionEvent`) | Yes | N/A |
| `soothe.error.*` / error custom event payloads | `query_engine.py` timeout/cancel/exception branches (`mode="custom"`) | Yes | N/A |

## Notes

- `output_streaming.mode` (`streaming` vs `batch`) is currently a client display policy concern for goal-completion stream chunks; daemon forwarding is gated by `output_streaming.enabled`, not by mode.
- For agentic execute phase, daemon contract is now explicit: forward tool telemetry, suppress execute-phase assistant prose.
