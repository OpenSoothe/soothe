# Daemon Event Forwarding Matrix

This matrix describes the current daemon-side forwarding contract from
`SootheRunner.astream()` to client transports.

Base transport rule:

- `QueryEngine` forwards every chunk emitted by the runner as `{type:"event", mode, data}`.
- Suppression primarily happens upstream in runner/StrangeLoop emission paths.

## Matrix (event_type -> source -> forwarded? -> suppression reason)

| event_type | source | forwarded? | suppression reason |
| --- | --- | --- | --- |
| `soothe.cognition.strange_loop.started` | `_runner_strange_loop.py::_run_strange_loop` (`StrangeLoopStartedEvent`) | Yes | N/A |
| `iteration_started` (raw StrangeLoop internal) | `strange_loop.py::run_with_progress` -> `_runner_strange_loop.py` branch | No | Internal debug-only; runner logs only, does not `yield` |
| `plan_decision` (raw StrangeLoop internal) | `strange_loop.py::run_with_progress` -> `_runner_strange_loop.py` branch | No | Internal debug-only; runner logs only, does not `yield` |
| `soothe.cognition.strange_loop.step.started` | `_runner_strange_loop.py` maps `step_started` -> `StrangeLoopStepStartedEvent` | Yes | N/A |
| `soothe.cognition.strange_loop.step.completed` | `_runner_strange_loop.py` maps `step_completed` -> `StrangeLoopStepCompletedEvent` | Yes | N/A |
| `stream_event` carrying `ToolMessage` | `strange_loop.py` emits `stream_event`; `_runner_strange_loop.py::_forward_messages_chunk_for_tool_ui` | Yes | N/A |
| `stream_event` carrying AI tool-invocation metadata (`tool_calls` / `tool_call_chunks`) | Same as above | Yes | N/A |
| `stream_event` carrying plain execute-phase assistant prose | Same as above | No | IG-304 daemon-side suppression: tool-only forwarding for `stream_event` |
| `stream_event` / `mode="messages"` loop-tagged AI with `phase` in `{goal_completion, quiz, autonomous_goal, direct_model}` | `_runner_strange_loop.py` forwards tagged assistant chunks from StrangeLoop (`stream_event`) | Yes (subject to client `output_streaming` display policy) | User-visible answer text path (IG-317); not emitted as `soothe.output.goal_completion.*` |
| `soothe.output.execution.streaming` | Legacy name; not emitted in current agentic path | No | IG-304: execute prose not wrapped as output-domain events |
| `soothe.output.goal_completion.streaming` / `soothe.output.goal_completion.responded` | Removed for core-loop assistant text (IG-317) | No | Superseded by `messages` + `phase` forwarding |
| `soothe.cognition.strange_loop.reasoned` | `_runner_strange_loop.py` maps `plan` -> `LoopAgentReasonEvent` | Conditional Yes | Suppressed when `status=="done"` and `next_action=="Goal achieved successfully"` |
| `iteration_completed` (raw StrangeLoop internal) | `strange_loop.py::run_with_progress` -> `_runner_strange_loop.py` branch | No | Internal debug-only; runner logs only, does not `yield` |
| `fatal_error` (raw StrangeLoop internal) | `strange_loop.py::run_with_progress` can emit `fatal_error`; `_runner_strange_loop.py` has no handling branch | No | Dropped due to missing forward mapping in runner |
| `soothe.cognition.strange_loop.completed` | `_runner_strange_loop.py` in `completed` branch (`StrangeLoopCompletedEvent`) | Yes | N/A |
| Historical `soothe.output.*` assistant duplicates (`goal_completion`, `quiz`, autonomous variants) | Removed with IG-317 hard cut (same bodies on `messages` + `phase`) | No | Matrix rows retained for archaeology only; do not expect these types for assistant text |
| `soothe.output.{source}` (dynamic) | `soothe.utils.output_capture.OutputCapture` when `emit_progress=True` | If enabled | Optional library line capture; not the main answer contract |
| `soothe.error.*` / error custom event payloads | `query_engine.py` timeout/cancel/exception branches (`mode="custom"`) | Yes | N/A |

## Notes

- `output_streaming.mode` (`streaming` vs `batch`) is currently a client display policy concern for goal-completion stream chunks; daemon forwarding is gated by `output_streaming.enabled`, not by mode.
- For agentic execute phase, daemon contract is now explicit: forward tool telemetry, suppress execute-phase assistant prose.
