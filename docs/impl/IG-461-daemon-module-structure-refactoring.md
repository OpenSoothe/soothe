# IG-461: Daemon Module Structure Refactoring

**RFC**: [RFC-623](../specs/RFC-623-daemon-module-structure-refactoring.md)
**Status**: Draft
**Created**: 2026-06-02
**Depends on**: RFC-623, RFC-450, RFC-454, RFC-620
**Related**: RFC-610 (companion `soothe-sdk` refactor)

---

## 1. Goal

Implement the structural refactor specified in RFC-623:

- Consolidate 11 in-scope root-level files into 3 new packages (`bootstrap/`, `server/`, `runtime/`) plus one root-level `cli.py`.
- Dissolve 4 single-file packages (`session/`, `rpc/`, `cli/`) by folding into `server/`; promote `services/` from single-file to multi-file by absorbing `image_understanding.py`.
- Split `server.py` (1417 LOC) + `_handlers.py` (296 LOC) into a 7-file `server/` package using mixin composition.
- Drop underscore-prefixed exports from `__init__.py` files (`rpc/_cmd_*`, `_handle_*`, `_send_command_response`).
- Promote two `protocol/router.py` private helpers (`_coerce_loop_input_text`, `_queue_options_from_daemon_message`) to public `protocol/__init__.py` exports.
- Enforce "no cross-package deep imports" — all callers go through package roots.
- Move daemon test files to mirror the new source structure.

Out of scope: `channels/` package and root `channel_manager.py` — unchanged.

---

## 2. Module layout

### 2.1 New directories

```
packages/soothe-daemon/src/soothe_daemon/
├── bootstrap/                          # NEW
│   ├── __init__.py                     # exports: bootstrap_dotenv, load_dotenv_adjacent_to_yaml,
│   │                                   #          default_daemon_log_path, pid_path, write_pid,
│   │                                   #          cleanup_pid, run_daemon, set_client_id, set_loop_id
│   ├── env.py                          # ← root bootstrap_env.py
│   ├── entrypoint.py                   # ← root entrypoint.py
│   ├── logging.py                      # ← root logging.py
│   ├── paths.py                        # ← root paths.py
│   └── singleton.py                    # ← root singleton.py
│
├── server/                             # NEW
│   ├── __init__.py                     # exports: SootheDaemon, DaemonProcess
│   ├── core.py                         # SootheDaemon class shell + construction
│   ├── lifecycle.py                    # LifecycleMixin (start/stop/serve_forever + 8 periodic tasks)
│   ├── transport.py                    # TransportMixin (connection handling, dispatch, broadcast)
│   ├── handlers.py                     # ← root _handlers.py (DaemonHandlersMixin)
│   ├── session.py                      # ← session/manager.py (ClientSession, ClientSessionManager)
│   ├── commands.py                     # ← rpc/handlers.py (with underscore renames)
│   └── process.py                      # DaemonProcess (is_running, find_pid, stop_running, ...)
│
├── runtime/                            # NEW
│   ├── __init__.py                     # exports: LoopInputDispatcher, ThreadState,
│   │                                   #          ThreadStateRegistry, bind_execution_thread_for_loop
│   ├── loop_dispatcher.py              # ← root loop_isolation.py
│   ├── loop_gc.py                      # ← root loop_gc.py (internal — no __all__ entries)
│   └── thread_state.py                 # ← root thread_state.py
│
├── services/                           # PROMOTED (was single-file)
│   ├── __init__.py                     # exports: run_direct_llm_turn, run_image_to_text_turn,
│   │                                   #          enrich_user_text_with_vision,
│   │                                   #          validate_and_normalize_image_attachments
│   ├── direct_llm_turn.py              # unchanged
│   └── image_understanding.py          # ← root image_understanding.py
│
├── cli.py                              # ← cli/daemon_main.py (now a root module, not a package)
└── channel_manager.py                  # UNCHANGED (out of scope)
```

### 2.2 Deleted

```
session/                  # entire directory (manager.py moved to server/session.py)
rpc/                      # entire directory (handlers.py moved to server/commands.py)
cli/                      # entire directory (daemon_main.py flattened to cli.py)
_handlers.py              # moved to server/handlers.py
server.py                 # split into server/{core,lifecycle,transport,process}.py
bootstrap_env.py          # moved to bootstrap/env.py
entrypoint.py             # moved to bootstrap/entrypoint.py
logging.py                # moved to bootstrap/logging.py
paths.py                  # moved to bootstrap/paths.py
singleton.py              # moved to bootstrap/singleton.py
loop_isolation.py         # moved to runtime/loop_dispatcher.py
loop_gc.py                # moved to runtime/loop_gc.py
thread_state.py           # moved to runtime/thread_state.py
image_understanding.py    # moved to services/image_understanding.py
```

### 2.3 Unchanged (existing well-formed packages, structure preserved)

```
channels/        # OUT OF SCOPE — no touch
config/          # __init__.py audited; structure unchanged
event/           # __init__.py audited; structure unchanged
health/          # __init__.py audited; structure unchanged
persistence/     # __init__.py audited; structure unchanged
protocol/        # __init__.py adds 2 promoted exports; structure unchanged
query/           # __init__.py adds StreamDeliveryMode; structure unchanged
runner/          # __init__.py audited; structure unchanged
```

---

## 3. server.py split (the one content split)

Source: `server.py` (1417 LOC) + `_handlers.py` (296 LOC). Target: 7 files in `server/`.

| New file | Concern | Source lines | Approx. LOC |
|----------|---------|--------------|-------------|
| `server/core.py` | `SootheDaemon` class shell, `__init__`, public methods, `_ClientConn`, `_log_startup_banner`, `daemon_ready_message`, `_get_handshake_messages`, `_cancel_loop_for_session` | `server.py` 45–198, 504–532 | ~250 |
| `server/lifecycle.py` | `LifecycleMixin`: `start`, `request_stop`, `_detect_incomplete_threads`, `serve_forever`, 8× `_periodic_*`, `_suspend_inactive_threads`, `stop` | `server.py` 199–503, 574–1075 | ~700 |
| `server/transport.py` | `TransportMixin`: `_is_port_live`, `_broadcast`, `_send`, `_handle_transport_message`, `_dispatch_with_semaphore`, `_cleanup_dispatch_tasks` | `server.py` 533–573, 1076–1190 | ~350 |
| `server/handlers.py` | `DaemonHandlersMixin` — verbatim content from `_handlers.py` | `_handlers.py` 1–end | ~290 |
| `server/process.py` | `DaemonProcess` class: `is_running`, `find_pid`, `_find_port_process`, `stop_running`, `_wait_for_pid_exit` (`@staticmethod` / `@classmethod`) | `server.py` 1191–end | ~200 |
| `server/session.py` | `ClientSession`, `ClientSessionManager` — verbatim from `session/manager.py` | `session/manager.py` 1–end | 736 |
| `server/commands.py` | All `cmd_*`, `handle_command_request`, `send_command_response` — verbatim from `rpc/handlers.py` with underscore prefix dropped on the names listed in §4.2 | `rpc/handlers.py` 1–end | 405 |

### Mixin composition

```python
# server/core.py (skeleton)
from soothe_daemon.server.handlers import DaemonHandlersMixin
from soothe_daemon.server.lifecycle import LifecycleMixin
from soothe_daemon.server.transport import TransportMixin


class SootheDaemon(LifecycleMixin, TransportMixin, DaemonHandlersMixin):
    """Soothe daemon server — background agent runner with WebSocket IPC."""

    def __init__(self, ...):
        # Construction only. All other methods live on mixins.
        ...
```

**MRO order rationale:** `LifecycleMixin` first (calls into transport for broadcasting; calls into handlers indirectly via `_query_engine`); `TransportMixin` second (calls into handlers); `DaemonHandlersMixin` last (already exists as a mixin today — minimal change).

**No method-name collisions:** verified by listing all methods per file in §3 above. All mixins target `object`.

### `DaemonProcess` extraction

The five static methods at the bottom of `server.py` (`is_running`, `find_pid`, `stop_running`, `_find_port_process`, `_wait_for_pid_exit`) don't depend on a daemon instance. Today they live as `@staticmethod`/`@classmethod` on `SootheDaemon` — move to a standalone class:

```python
# server/process.py
class DaemonProcess:
    """PID-file-based daemon process discovery and shutdown."""

    @staticmethod
    def is_running() -> bool: ...

    @staticmethod
    def find_pid() -> int | None: ...

    @staticmethod
    def stop_running(timeout: float = _STOP_TIMEOUT_S) -> bool: ...

    # Internal helpers — keep underscore
    @staticmethod
    def _find_port_process(port: int) -> int | None: ...

    @staticmethod
    def _wait_for_pid_exit(pid: int, timeout: float) -> bool: ...
```

Callers in `cli.py` change from `SootheDaemon.is_running()` to `DaemonProcess.is_running()`.

---

## 4. API tightening

### 4.1 Package `__init__.py` definitions

#### `soothe_daemon/__init__.py` (unchanged behaviorally; internal import paths updated)

```python
"""Soothe daemon subpackage - background agent runner with WebSocket IPC."""

import importlib.metadata

try:
    __version__ = importlib.metadata.version("soothe-daemon")
except importlib.metadata.PackageNotFoundError:
    __version__ = "0.0.0"

from soothe_sdk.client import WebSocketClient

from soothe_daemon.bootstrap import pid_path, run_daemon
from soothe_daemon.server import SootheDaemon

__all__ = ["SootheDaemon", "WebSocketClient", "__version__", "pid_path", "run_daemon"]
```

#### `soothe_daemon/bootstrap/__init__.py`

```python
"""Process startup primitives for the daemon."""

from soothe_daemon.bootstrap.entrypoint import run_daemon
from soothe_daemon.bootstrap.env import bootstrap_dotenv, load_dotenv_adjacent_to_yaml
from soothe_daemon.bootstrap.logging import (
    default_daemon_log_path,
    set_client_id,
    set_loop_id,
)
from soothe_daemon.bootstrap.paths import pid_path
from soothe_daemon.bootstrap.singleton import cleanup_pid, write_pid

__all__ = [
    "bootstrap_dotenv",
    "cleanup_pid",
    "default_daemon_log_path",
    "load_dotenv_adjacent_to_yaml",
    "pid_path",
    "run_daemon",
    "set_client_id",
    "set_loop_id",
    "write_pid",
]
```

#### `soothe_daemon/server/__init__.py`

```python
"""The running daemon: SootheDaemon class plus PID-based process discovery."""

from soothe_daemon.server.core import SootheDaemon
from soothe_daemon.server.process import DaemonProcess

__all__ = ["DaemonProcess", "SootheDaemon"]
```

Internal-only (not exported): `LifecycleMixin`, `TransportMixin`, `DaemonHandlersMixin`, `ClientSession`, `ClientSessionManager`, `cmd_*` (14 functions), `handle_command_request`, `send_command_response`, `_ClientConn`, `_log_startup_banner`.

#### `soothe_daemon/runtime/__init__.py`

```python
"""Daemon-side asyncio runtime primitives (per-loop dispatch, thread state, GC)."""

from soothe_daemon.runtime.loop_dispatcher import (
    LoopInputDispatcher,
    bind_execution_thread_for_loop,
)
from soothe_daemon.runtime.thread_state import ThreadState, ThreadStateRegistry

__all__ = [
    "LoopInputDispatcher",
    "ThreadState",
    "ThreadStateRegistry",
    "bind_execution_thread_for_loop",
]
```

`loop_gc.py` helpers are called only from `server/lifecycle.py` (`_periodic_ephemeral_loop_gc` calls `_cancel_and_detach_loop` and `_delete_loop_threads`). Two options:

- **Option A (chosen):** export `cancel_and_detach_loop` and `delete_loop_threads` from `runtime/__init__.py` (drop underscore — they're public-shaped for cross-package use).
- **Option B (rejected):** keep them underscored and call via deep import. Rejected because deep imports violate §6.3 of RFC-623.

Final `runtime/__init__.py`:

```python
"""Daemon-side asyncio runtime primitives (per-loop dispatch, thread state, GC)."""

from soothe_daemon.runtime.loop_dispatcher import (
    LoopInputDispatcher,
    bind_execution_thread_for_loop,
)
from soothe_daemon.runtime.loop_gc import (
    cancel_and_detach_loop,
    delete_loop_threads,
)
from soothe_daemon.runtime.thread_state import ThreadState, ThreadStateRegistry

__all__ = [
    "LoopInputDispatcher",
    "ThreadState",
    "ThreadStateRegistry",
    "bind_execution_thread_for_loop",
    "cancel_and_detach_loop",
    "delete_loop_threads",
]
```

(The two `loop_gc` helpers — currently `_cancel_and_detach_loop` and `_delete_loop_threads` — drop their underscore prefix as part of this refactor.)

#### `soothe_daemon/services/__init__.py`

```python
"""Daemon-local services: direct LLM calls that bypass the Soothe agent graph."""

from soothe_daemon.services.direct_llm_turn import (
    run_direct_llm_turn,
    run_image_to_text_turn,
)
from soothe_daemon.services.image_understanding import (
    enrich_user_text_with_vision,
    validate_and_normalize_image_attachments,
)

__all__ = [
    "enrich_user_text_with_vision",
    "run_direct_llm_turn",
    "run_image_to_text_turn",
    "validate_and_normalize_image_attachments",
]
```

Internal-only (intra-package): `_build_vision_invoke_config`, `_build_direct_invoke_config`, other underscore helpers in both files.

#### `soothe_daemon/protocol/__init__.py` (audited: add 2)

```python
"""Protocol infrastructure for daemon communication (RFC-450)."""

from soothe_daemon.protocol.router import (
    MessageRouter,
    coerce_loop_input_text,                  # was _coerce_loop_input_text
    queue_options_from_daemon_message,       # was _queue_options_from_daemon_message
)
from soothe_daemon.protocol.validation import (
    ERROR_INTERNAL_ERROR,
    ERROR_INVALID_JSON,
    ERROR_INVALID_MESSAGE,
    ERROR_RATE_LIMITED,
    ERROR_UNKNOWN_MESSAGE_TYPE,
    ProtocolError,
    create_error_response,
    validate_message,
    validate_message_size,
)

__all__ = [
    "ERROR_INTERNAL_ERROR",
    "ERROR_INVALID_JSON",
    "ERROR_INVALID_MESSAGE",
    "ERROR_RATE_LIMITED",
    "ERROR_UNKNOWN_MESSAGE_TYPE",
    "MessageRouter",
    "ProtocolError",
    "coerce_loop_input_text",
    "create_error_response",
    "queue_options_from_daemon_message",
    "validate_message",
    "validate_message_size",
]
```

#### `soothe_daemon/query/__init__.py` (audited: add `StreamDeliveryMode`)

```python
"""Query execution infrastructure for the daemon."""

from soothe_daemon.query.engine import QueryEngine
from soothe_daemon.query.stream_delivery import StreamDeliveryMode

__all__ = ["QueryEngine", "StreamDeliveryMode"]
```

#### Existing package `__init__.py` audits

| Package | Current exports | Audit action |
|---------|-----------------|--------------|
| `config/` | 12 names | Verified usage via `rg "from soothe_daemon.config import"`; drop names not imported anywhere outside `config/`. Likely keep at least: `SootheDaemonConfig`, `default_daemon_config_path`, `default_soothe_config_path`, `apply_env_overrides`. Audit during commit 5. |
| `event/` | 4 names (`EventBus`, `EventSizeDistributionCollector`, `handle_loop_reattach`, `loop_event_topic`) | Audit; all likely retained. |
| `health/` | 8 names | Audit; `cli.py` (the consumer) uses `HealthChecker`, `format_json/markdown/text`, `CheckStatus`. Other 4 likely retained for completeness. |
| `persistence/` | 11 names | Audit; drop names with no external imports. |
| `runner/` | 1 name (`LoopRunnerFactory`) | Already minimal — keep. |

### 4.2 Underscore-prefix renames

In `server/commands.py` (was `rpc/handlers.py`):

```
_cmd_autopilot_dashboard       → cmd_autopilot_dashboard
_cmd_cancel                    → cmd_cancel
_cmd_clear                     → cmd_clear
_cmd_config                    → cmd_config
_cmd_detach                    → cmd_detach
_cmd_exit                      → cmd_exit
_cmd_history                   → cmd_history
_cmd_memory                    → cmd_memory
_cmd_plan                      → cmd_plan
_cmd_policy                    → cmd_policy
_cmd_quit                      → cmd_quit
_cmd_resume                    → cmd_resume
_cmd_review                    → cmd_review
_cmd_thread                    → cmd_thread
_handle_command_request        → handle_command_request
_send_command_response         → send_command_response
```

Sole caller after the refactor: `server/handlers.py` (was `_handlers.py`). Update the import there.

In `protocol/router.py`:

```
_coerce_loop_input_text                → coerce_loop_input_text
_queue_options_from_daemon_message     → queue_options_from_daemon_message
```

Both currently called from `_handlers.py` line 25–28. After move, the caller is `server/handlers.py`; update its import to `from soothe_daemon.protocol import …` (package root, not `protocol.router`).

In `runtime/loop_gc.py` (was `loop_gc.py`):

```
_cancel_and_detach_loop        → cancel_and_detach_loop
_delete_loop_threads           → delete_loop_threads
```

Sole caller: `server/lifecycle.py`'s `_periodic_ephemeral_loop_gc` (was `server.py`'s same method). Update the import to `from soothe_daemon.runtime import …`.

### 4.3 Cross-package import rule

All cross-package imports use package roots:

```python
# server/handlers.py — internal-to-server uses sibling submodule
from soothe_daemon.server.session import ClientSessionManager  # OK (intra-package)
from soothe_daemon.server.commands import cmd_cancel, ...      # OK (intra-package)

# server/handlers.py — cross-package goes through package root
from soothe_daemon.protocol import coerce_loop_input_text      # OK
from soothe_daemon.protocol.router import coerce_loop_input_text  # FORBIDDEN
```

Enforcement: post-refactor `rg` sweep to confirm no `from soothe_daemon.<pkg>.<deep>` imports cross package boundaries.

---

## 5. File migration mapping

### 5.1 Pure `git mv` operations (13)

| From | To | Notes |
|------|----|-------|
| `src/soothe_daemon/bootstrap_env.py` | `src/soothe_daemon/bootstrap/env.py` | Rename + move |
| `src/soothe_daemon/entrypoint.py` | `src/soothe_daemon/bootstrap/entrypoint.py` | Move |
| `src/soothe_daemon/logging.py` | `src/soothe_daemon/bootstrap/logging.py` | Move |
| `src/soothe_daemon/paths.py` | `src/soothe_daemon/bootstrap/paths.py` | Move |
| `src/soothe_daemon/singleton.py` | `src/soothe_daemon/bootstrap/singleton.py` | Move |
| `src/soothe_daemon/loop_isolation.py` | `src/soothe_daemon/runtime/loop_dispatcher.py` | Rename + move |
| `src/soothe_daemon/loop_gc.py` | `src/soothe_daemon/runtime/loop_gc.py` | Move |
| `src/soothe_daemon/thread_state.py` | `src/soothe_daemon/runtime/thread_state.py` | Move |
| `src/soothe_daemon/image_understanding.py` | `src/soothe_daemon/services/image_understanding.py` | Move |
| `src/soothe_daemon/session/manager.py` | `src/soothe_daemon/server/session.py` | Rename + move |
| `src/soothe_daemon/rpc/handlers.py` | `src/soothe_daemon/server/commands.py` | Rename + move |
| `src/soothe_daemon/cli/daemon_main.py` | `src/soothe_daemon/cli.py` | Flatten to root module |
| `src/soothe_daemon/_handlers.py` | `src/soothe_daemon/server/handlers.py` | Drop underscore + move |

After moves, run:

```bash
rmdir packages/soothe-daemon/src/soothe_daemon/session
rmdir packages/soothe-daemon/src/soothe_daemon/rpc
rmdir packages/soothe-daemon/src/soothe_daemon/cli
```

### 5.2 Content split

`src/soothe_daemon/server.py` (1417 LOC) → 4 new files in `src/soothe_daemon/server/`:
- `core.py` (~250 LOC)
- `lifecycle.py` (~700 LOC)
- `transport.py` (~350 LOC)
- `process.py` (~200 LOC)

Delete original `server.py` after split.

### 5.3 Test file mapping

Current daemon tests live mostly in `tests/unit/daemon/` — a flat directory that doesn't mirror the new source structure. Remap per project rule ("tests live in package's test directory matching source").

| Existing test | New location | Reason |
|---------------|--------------|--------|
| `tests/unit/daemon/test_bootstrap_env.py` | `tests/unit/bootstrap/test_env.py` | Source moved to `bootstrap/env.py` |
| `tests/unit/test_daemon_logging.py` | `tests/unit/bootstrap/test_logging.py` | Source moved to `bootstrap/logging.py` |
| `tests/unit/daemon/test_loop_isolation_resume.py` | `tests/unit/runtime/test_loop_dispatcher.py` | Source moved + renamed |
| `tests/unit/daemon/test_ephemeral_loop_gc.py` | `tests/unit/runtime/test_loop_gc.py` | Source moved |
| `tests/unit/daemon/test_thread_manager.py` | `tests/unit/runtime/test_thread_state.py` | Source moved |
| `tests/unit/daemon/test_image_understanding.py` | `tests/unit/services/test_image_understanding.py` | Source moved |
| `tests/unit/daemon/test_vision_preflight_throttle.py` | `tests/unit/services/test_vision_preflight_throttle.py` | Same package |
| `tests/unit/daemon/test_direct_llm_turn.py` | `tests/unit/services/test_direct_llm_turn.py` | Source unchanged path, just relocate test |
| `tests/unit/daemon/test_client_session.py` | `tests/unit/server/test_session.py` | Source moved to `server/session.py` |
| `tests/unit/daemon/test_message_router_command_request.py` | `tests/unit/server/test_commands.py` (or stays in protocol/) | Tests command request routing — fits `server/commands` better |
| `tests/unit/daemon/test_daemon_lifecycle.py` | `tests/unit/server/test_lifecycle.py` | Source moved to `server/lifecycle.py` |
| `tests/unit/daemon/test_broadcast_internal.py` | `tests/unit/server/test_transport.py` | Source moved to `server/transport.py` |
| `tests/unit/daemon/test_transport_abstraction.py` | `tests/unit/server/test_transport.py` (merge or rename) | Same concern |
| `tests/unit/daemon/test_process_cleanup.py` | `tests/unit/persistence/test_process_cleanup.py` | Source is in `persistence/` (unchanged) |
| `tests/unit/daemon/test_event_bus.py` | `tests/unit/event/test_bus.py` | Source in `event/` (unchanged) |
| `tests/unit/daemon/event_size_stats/test_estimator.py` | `tests/unit/event/test_size_stats.py` | Source in `event/` (unchanged) |
| `tests/unit/daemon/test_stream_delivery.py` | `tests/unit/query/test_stream_delivery.py` | Source in `query/` (unchanged) |
| `tests/unit/daemon/test_query_engine_cancel.py` | `tests/unit/query/test_engine_cancel.py` | Source in `query/` (unchanged) |
| `tests/unit/daemon/test_message_router_loop_input.py` | `tests/unit/protocol/test_router_loop_input.py` | Source in `protocol/` (unchanged) |
| `tests/unit/daemon/test_message_router_models.py` | `tests/unit/protocol/test_validation.py` | Tests message validation models |
| `tests/unit/daemon/test_message_router_skills.py` | `tests/unit/protocol/test_router_skills.py` | Source in `protocol/` |
| `tests/unit/daemon/test_protocol_v2.py` | `tests/unit/protocol/test_protocol_v2.py` | Source in `protocol/` |
| `tests/unit/daemon/test_delivery_drain.py` | `tests/unit/query/test_delivery_drain.py` (or `tests/unit/server/`) | Stream delivery drain — query package |
| `tests/unit/daemon/test_subscribe_autopilot_filter.py` | `tests/unit/server/test_subscribe_filter.py` | Session subscription concern |
| `tests/unit/daemon/test_thread_deletion.py` | `tests/unit/server/test_thread_deletion.py` | Server-level thread management |
| `tests/unit/daemon/test_loop_new_client_workspace.py` | `tests/unit/server/test_loop_new_client_workspace.py` | Server-level loop wiring |
| `tests/unit/daemon/test_scheduler_service.py` | `tests/unit/server/test_scheduler_service.py` (or keep in daemon/) | If scheduler is server concern |
| `tests/unit/daemon/test_webhook_service.py` | (location depends on webhook source location) | TBD during commit |
| `tests/unit/daemon/test_pool_sizing.py` | `tests/unit/persistence/test_pool_sizing.py` | Source in `persistence/` |
| `tests/unit/daemon/health/test_embedding_warmup_check.py` | `tests/unit/health/checks/test_embedding_warmup_check.py` | Source in `health/checks/` |
| `tests/unit/daemon/persistence/test_periodic_stale_worker_reap.py` | `tests/unit/persistence/test_process_cleanup_periodic.py` | Source in `persistence/` |
| `tests/unit/cli/test_cli_daemon.py` | `tests/unit/test_cli.py` (or `tests/unit/cli/test_cli.py` if multi-file expected) | Source flattened to `cli.py` |
| `tests/unit/cli/test_daemon_main_cli.py` | merge into `tests/unit/test_cli.py` or keep as `tests/unit/cli/test_daemon_main.py` | Same module |

After remapping, the `tests/unit/daemon/` directory is largely empty (or eliminated). The following directories appear/remain under `tests/unit/`:

```
tests/unit/
├── bootstrap/         # NEW
├── channels/          # UNCHANGED (out of scope)
├── event/             # NEW
├── health/            # NEW (with checks/ subdir)
├── persistence/       # NEW
├── protocol/          # NEW
├── query/             # NEW
├── runner/            # EXISTS
├── runtime/           # NEW
├── server/            # NEW
└── services/          # NEW
```

The flat `tests/unit/daemon/` and one-off root `tests/unit/test_daemon_logging.py` go away.

### 5.4 Import sweep

Mechanical via ripgrep + sed. Run from repo root after all `git mv`:

```bash
TARGETS=(
  packages/soothe-daemon/src/soothe_daemon
  packages/soothe-daemon/tests
  scripts
)

rg -l "from soothe_daemon\.\(bootstrap_env\|entrypoint\|logging\|paths\|singleton\|loop_gc\|loop_isolation\|thread_state\|image_understanding\|session\|rpc\|cli\|_handlers\|server\)\b" "${TARGETS[@]}" | xargs sed -i '' \
  -e 's|from soothe_daemon\.bootstrap_env |from soothe_daemon.bootstrap.env |g' \
  -e 's|from soothe_daemon\.entrypoint |from soothe_daemon.bootstrap.entrypoint |g' \
  -e 's|from soothe_daemon\.logging |from soothe_daemon.bootstrap.logging |g' \
  -e 's|from soothe_daemon\.paths |from soothe_daemon.bootstrap.paths |g' \
  -e 's|from soothe_daemon\.singleton |from soothe_daemon.bootstrap.singleton |g' \
  -e 's|from soothe_daemon\.loop_isolation |from soothe_daemon.runtime.loop_dispatcher |g' \
  -e 's|from soothe_daemon\.loop_gc |from soothe_daemon.runtime.loop_gc |g' \
  -e 's|from soothe_daemon\.thread_state |from soothe_daemon.runtime.thread_state |g' \
  -e 's|from soothe_daemon\.image_understanding |from soothe_daemon.services.image_understanding |g' \
  -e 's|from soothe_daemon\.session import |from soothe_daemon.server import |g' \
  -e 's|from soothe_daemon\.session\.manager |from soothe_daemon.server.session |g' \
  -e 's|from soothe_daemon\.rpc import |from soothe_daemon.server import |g' \
  -e 's|from soothe_daemon\.rpc\.handlers |from soothe_daemon.server.commands |g' \
  -e 's|from soothe_daemon\.cli\.daemon_main |from soothe_daemon.cli |g' \
  -e 's|from soothe_daemon\._handlers |from soothe_daemon.server.handlers |g'
```

Then promote-and-tidy:

```bash
# Promote protocol router private helpers to public exports
rg -l "_coerce_loop_input_text\|_queue_options_from_daemon_message" "${TARGETS[@]}" | xargs sed -i '' \
  -e 's|from soothe_daemon\.protocol\.router import _coerce_loop_input_text|from soothe_daemon.protocol import coerce_loop_input_text|g' \
  -e 's|from soothe_daemon\.protocol\.router import _queue_options_from_daemon_message|from soothe_daemon.protocol import queue_options_from_daemon_message|g' \
  -e 's|_coerce_loop_input_text|coerce_loop_input_text|g' \
  -e 's|_queue_options_from_daemon_message|queue_options_from_daemon_message|g'

# Promote loop_gc private helpers
sed -i '' \
  -e 's|_cancel_and_detach_loop|cancel_and_detach_loop|g' \
  -e 's|_delete_loop_threads|delete_loop_threads|g' \
  packages/soothe-daemon/src/soothe_daemon/runtime/loop_gc.py \
  packages/soothe-daemon/src/soothe_daemon/server/lifecycle.py

# Drop _cmd_* / _handle_command_request / _send_command_response underscores in commands + sole caller
sed -i '' \
  -e 's|_cmd_autopilot_dashboard|cmd_autopilot_dashboard|g' \
  -e 's|_cmd_cancel|cmd_cancel|g' \
  -e 's|_cmd_clear|cmd_clear|g' \
  -e 's|_cmd_config|cmd_config|g' \
  -e 's|_cmd_detach|cmd_detach|g' \
  -e 's|_cmd_exit|cmd_exit|g' \
  -e 's|_cmd_history|cmd_history|g' \
  -e 's|_cmd_memory|cmd_memory|g' \
  -e 's|_cmd_plan|cmd_plan|g' \
  -e 's|_cmd_policy|cmd_policy|g' \
  -e 's|_cmd_quit|cmd_quit|g' \
  -e 's|_cmd_resume|cmd_resume|g' \
  -e 's|_cmd_review|cmd_review|g' \
  -e 's|_cmd_thread|cmd_thread|g' \
  -e 's|_handle_command_request|handle_command_request|g' \
  -e 's|_send_command_response|send_command_response|g' \
  packages/soothe-daemon/src/soothe_daemon/server/commands.py \
  packages/soothe-daemon/src/soothe_daemon/server/handlers.py
```

**Caveat:** the sed substitutions for underscore removal are scoped only to `server/commands.py` + `server/handlers.py` (the two files that use those names). The names are unique enough that wider replacement is safe, but scoped is safer.

### 5.5 External consumer update

```python
# scripts/verify_daemon_events.py line 35
# Before:
from soothe_daemon.query.stream_delivery import StreamDeliveryMode
# After:
from soothe_daemon.query import StreamDeliveryMode
```

---

## 6. Implementation phases (single PR, 6 sequenced commits)

### Commit 1 — skeletons

```bash
mkdir -p packages/soothe-daemon/src/soothe_daemon/{bootstrap,server,runtime}
mkdir -p packages/soothe-daemon/tests/unit/{bootstrap,server,runtime,services,event,health,health/checks,persistence,protocol,query}
```

Create empty `__init__.py` in each new src package (with `__all__ = []` placeholder) and each new test directory. Tests still pass (nothing imports from new paths yet).

### Commit 2 — pure relocations + import sweep

Execute `git mv` for 13 files (§5.1). Remove empty `session/`, `rpc/`, `cli/` source directories. Move test files per §5.3 mapping using `git mv`. Run import sweep (§5.4 first sed block). Populate new package `__init__.py` files per §4.1.

Verify: `./scripts/verify_finally.sh` passes. `pytest packages/soothe-daemon/tests` collects same test count as before.

### Commit 3 — split `server.py`

Carve `server/core.py`, `server/lifecycle.py`, `server/transport.py`, `server/process.py` from `server.py`. Wire `SootheDaemon` with three-mixin composition. Delete `server.py`. Update `cli.py` caller: `SootheDaemon.is_running()` → `DaemonProcess.is_running()` and similar (4 call sites).

Verify: `./scripts/verify_finally.sh` passes. Integration test `soothed start` / `soothed stop` round-trip works.

### Commit 4 — underscore renames

Apply §5.4 second and third sed blocks. Update `protocol/__init__.py`, `runtime/__init__.py`, and `server/commands.py` `__all__` lists to use new public names. Update `server/handlers.py` import lines.

Verify: `./scripts/verify_finally.sh` passes.

### Commit 5 — `__init__.py` audits

For each existing package (`config`, `event`, `health`, `persistence`, `runner`), grep cross-package usage:

```bash
for pkg in config event health persistence runner; do
  echo "=== $pkg ==="
  rg "from soothe_daemon\.$pkg import" packages/soothe-daemon/src/soothe_daemon \
    | grep -v "/$pkg/" | awk -F: '{print $3}' | sort -u
done
```

Trim each package's `__init__.py` `__all__` to the actual cross-package usage set. Update `query/__init__.py` to add `StreamDeliveryMode`.

Verify: `./scripts/verify_finally.sh` passes.

### Commit 6 — external consumer + final verification

Update `scripts/verify_daemon_events.py` (one line). Run the full validation sweep:

```bash
./scripts/verify_finally.sh
rg "from soothe_daemon\.(bootstrap_env|entrypoint|logging|paths|singleton|loop_gc|loop_isolation|thread_state|image_understanding|session|rpc|_handlers)\b" . --type py | grep -v thirdparty/ | grep -v .venv/
# expected: empty

rg "from soothe_daemon\.\w+\.\w+ import" . --type py | grep -v "packages/soothe-daemon/" | grep -v thirdparty/ | grep -v .venv/
# expected: empty (no external caller reaches into deep submodules)

rg "_cmd_|_handle_command_request|_send_command_response|_coerce_loop_input_text|_queue_options_from_daemon_message|_cancel_and_detach_loop|_delete_loop_threads" packages/soothe-daemon
# expected: empty (no underscore-prefixed names left for promoted helpers)
```

---

## 7. Risks & mitigations

| Risk | Mitigation |
|------|------------|
| **Circular import** between `server/core.py` ↔ `lifecycle.py` ↔ `transport.py` ↔ `handlers.py` after split | Mixins target `object`, not each other. Helpers go in `core.py`. Run `python -c "import soothe_daemon.server"` after commit 3 to catch cycles immediately. |
| **MRO collision** if two mixins define the same method name | Pre-audit: every method per file listed in §3. No collisions. Verify by `grep "    def \|    async def " server/{lifecycle,transport,handlers}.py | sort | uniq -d` returning empty. |
| **Missed import after sweep** | Run all 3 verification greps in commit 6. Run unit tests after each commit. Integration tests after commit 3 (server) and commit 6 (final). |
| **Test discovery breaks** when test files move | Use `git mv` (preserves path metadata). Before/after `pytest --collect-only` test count must match. Run after commit 2. |
| **`scripts/verify_finally.sh` doesn't catch a subtle behavior change** | Manual integration test: `soothed start` + `soothed status` + `soothed doctor` + send a query through `soothe-cli` + `soothed stop`. After commit 3 and commit 6. |
| **External plugin reaches into daemon internals** | Pre-refactor: `rg "from soothe_daemon" --type py | grep -v packages/soothe-daemon/`. Confirmed only `scripts/verify_daemon_events.py`. If a plugin appears, halt and re-scope. |
| **PID file locking changes after `DaemonProcess` extraction** | Behavior preservation: `DaemonProcess.is_running` / `find_pid` / `stop_running` keep identical logic — pure relocation. Test with existing `test_daemon_lifecycle.py` after move. |
| **LangGraph checkpoint references to `soothe_daemon.server.SootheDaemon`** | `server/__init__.py` re-exports `SootheDaemon`, so the import path resolves. Class `__module__` shifts from `soothe_daemon.server` → `soothe_daemon.server.core`; if any checkpoint test fails, add `SootheDaemon.__module__ = "soothe_daemon.server"` override in `server/__init__.py`. |

---

## 8. Testing strategy

### 8.1 Pre-refactor baseline

- `./scripts/verify_finally.sh` green.
- `pytest packages/soothe-daemon/tests --collect-only -q | tail -1` — record test count.
- `pytest packages/soothe-daemon/tests -x` — record pass count.
- `rg "from soothe_daemon" --type py | grep -v packages/soothe-daemon/ | grep -v thirdparty/ | grep -v .venv/` — confirm external consumer inventory (expected: 1 line).

### 8.2 Per-commit verification

After each of commits 1–6:

- `./scripts/verify_finally.sh` passes.
- Test count matches baseline.
- No new ruff/mypy errors.

### 8.3 Post-refactor validation (after commit 6)

- All unit tests pass (same count as baseline, modulo any tests deliberately consolidated).
- All integration tests pass: `pytest packages/soothe-daemon/tests/integration -m "not slow"`.
- Smoke test: `soothed start` → `soothed status` → small CLI query via `soothe-cli` → `soothed stop`. Verify daemon log shows clean startup / shutdown.
- Health check: `soothed doctor` runs all categories successfully.
- Deep-import verification grep returns empty (see commit 6).
- Underscore-prefix verification grep returns empty (see commit 6).

### 8.4 New tests added

None for this refactor — it's a pure structural change. All behavior is preserved.

---

## 9. Rollback

This is a single-PR refactor. Rollback = revert the PR. No DB migrations, no wire-protocol changes, no schema changes — pure code-organization shift. The companion update to `scripts/verify_daemon_events.py` reverts cleanly with the source revert.

---

## 10. Open mini-decisions tracked from RFC-623

| Decision | Resolution in this IG |
|----------|----------------------|
| `DaemonProcess` lives in `server/process.py` vs `bootstrap/singleton.py` | **`server/process.py`** (§3). PID *discovery* belongs with the server; PID *write/cleanup at start/stop* stays in `bootstrap/singleton.py`. |
| `loop_gc.py` helpers stay underscore-private vs become public | **Public** (§4.1 `runtime/__init__.py`). Their sole external caller (`server/lifecycle.py`) is in a different package, and §6.3 of RFC-623 forbids deep cross-package imports. Drop the underscore. |
| Composition vs mixins for the `server.py` split | **Mixins** (§3). Matches existing `class SootheDaemon(DaemonHandlersMixin)` pattern. A future RFC may convert to composition. |

---

## 11. Related documents

- [RFC-623](../specs/RFC-623-daemon-module-structure-refactoring.md) — Source RFC
- [RFC-610](../specs/RFC-610-sdk-module-structure-refactoring.md) — Companion SDK refactor (same philosophy)
- [RFC-450](../specs/RFC-450-daemon-communication-protocol.md) — Daemon Communication Protocol
- [RFC-454](../specs/RFC-454-slash-command-architecture.md) — Slash Command Architecture
- Brainstorming draft: `docs/drafts/2026-06-02-soothe-daemon-restructure-design.md`
