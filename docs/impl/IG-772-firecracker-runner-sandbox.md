# Implementation Guide: Firecracker microVM Runner Sandbox

**Guide**: IG-772
**Title**: Firecracker microVM Runner Sandbox
**Created**: 2026-09-02
**Related RFCs**: RFC-221 (Loop Runner Protocol), RFC-906 (Workspace Sync Architecture)

## Abstract

This guide documents the addition of a fourth `LoopRunnerProtocol` implementation —
`FirecrackerLoopRunner` — that executes Soothe agent loops inside AWS Firecracker
microVMs. It joins the existing thread (`ThreadLoopRunner`), process
(`PoolLoopRunner`), and Ray (`RayLoopRunner`) runners, selectable via daemon
config (`firecracker.enabled=True`).

## Motivation

The existing `worker_pool` mode provides process-level isolation via
`multiprocessing.spawn`. For workloads requiring stronger isolation (untrusted
agent code, multi-tenant hosting, compliance), a full VM boundary is desirable.
Firecracker microVMs boot in ~125ms–2s and provide hardware-enforced isolation
with minimal overhead, making them suitable as a warm-pooled execution substrate.

## Architecture

```
LoopRunnerFactory  (mode: thread_pool | worker_pool | distributed | firecracker)
    │
    ├── firecracker mode
    │       └── FirecrackerLoopRunner  (per loop_id, delegates to shared FirecrackerWorkerPool)
    │               └── FirecrackerWorkerPool  (warm pool of N microVMs)
    │                       ├── per-VM: firecracker process + vsock CID + guest worker
    │                       │     └── _pool_worker_body (reuse) → SootheRunner.astream()
    │                       │           │ chunks via vsock stream
    │                       │           ▼
    │                       │     _VsockStreamBridge (host side) → asyncio.Queue
    │                       └── submit(request) → async generator
    │
    └── (existing) thread_pool / worker_pool / distributed  — unchanged
```

No DAG boundary change: all new code lives in `soothe-daemon` (runner + config),
reusing `soothe.protocols.runner.LoopRunnerProtocol` (already in `soothe`).

## Components

### FirecrackerConfig (`config/models.py`)

Pydantic model with VM-specific fields: `kernel_image_path`,
`rootfs_image_path`, `firecracker_binary_path`, `min_pool_size`/`max_pool_size`,
`vsock_port_base`, `vm_cpu_count`, `vm_mem_mib`, `idle_timeout_seconds`,
`max_requests_per_worker`, `request_timeout_seconds`, `reuse_runner`,
`warmup_runner`, `warmup_core_agent`, `workspace_mount_mode`,
`extra_kernel_args`. Defaults: `enabled=False`, `min_pool_size=1`,
`max_pool_size=4`, `vsock_port_base=1024`, `vm_cpu_count=2`, `vm_mem_mib=2048`.

### _VsockStreamBridge (`runner/firecracker_runner.py`)

Host-side vsock reader. Opens a host-side vsock socket (CID 2, per-VM port =
`vsock_port_base + worker_index`), reads length-prefixed pickled frames (the
same 3-tuple `(msg_type, request_id, payload)` convention as
`response_bridge.WORKER_MSG_*`), and pushes them into an `asyncio.Queue` via
`loop.run_in_executor`. Cancel = send a `"cancel"` frame; force-kill = close
socket + kill VM.

Frame protocol: 4-byte big-endian length prefix + pickled payload bytes.
Import-safe on non-Linux (guards `AF_VSOCK` availability; raises
`RuntimeError` only when instantiated).

### FirecrackerWorkerPool (`runner/firecracker_runner.py`)

Singleton pool (`get_shared_instance`/`close_shared_instance`, mirroring
`WorkerPool`/`ThreadPool`). Pre-warms `min_pool_size` Firecracker VMs at daemon
startup. Each VM boots the configured kernel + rootfs, runs a guest-side
entrypoint that imports `_pool_worker_body` and speaks the vsock frame protocol.

- `submit(request)`: acquires an idle VM, sends the `LoopRunRequest` (pickled,
  spawn-safe via `spawn_safe_config`), returns the bridge's async generator.
- `cancel_request(loop_id)`: sends the cancel frame (cooperative).
- `force_kill_worker_by_loop_id(loop_id)`: shuts down the VM process (backstop).
- `is_loop_busy(loop_id)`: checks if a busy VM is mapped to this loop.

VM boot uses `subprocess.Popen` with an API socket (REST over UNIX socket) to
drive `boot-source`/`machine-config`/`vsock`/`drives` PUT calls.

### FirecrackerLoopRunner (`runner/firecracker_runner.py`)

Thin per-`loop_id` facade implementing `LoopRunnerProtocol`. Mirrors
`PoolLoopRunner`'s structure — delegates `run()` to `FirecrackerWorkerPool.submit()`,
`cancel()` to `pool.cancel_request()`, `is_idle()` to `not pool.is_loop_busy()`,
`force_kill()` to `pool.force_kill_worker_by_loop_id()`. `set_clarification_mode()`
returns `False` (VM isolation, same as `PoolLoopRunner`/`RayLoopRunner`).

### Factory wiring (`runner/factory.py`)

`LoopRunnerFactory.__init__` gains an `elif mode == "firecracker"` branch that
validates the `firecracker` binary is executable and kernel/rootfs paths exist
(fail fast, like the Ray import check). `get_shared_execution_pool`,
`initialize_pool`, `shutdown_pool`, and `create_runner` each gain a `firecracker`
branch with lazy imports. The identity-runtime incompatibility guard is extended
to cover `firecracker` (same spawn-isolation limitation as `worker_pool`).

## Data Flow

1. Daemon startup → `LoopRunnerFactory.initialize_pool()` →
   `FirecrackerWorkerPool.get_shared_instance()` → pre-warm `min_pool_size` VMs.
2. Each VM boots kernel + rootfs, guest entrypoint connects back over vsock.
3. `_VsockStreamBridge` accepts the connection, starts the reader task.
4. Query arrives → `FirecrackerLoopRunner.run(request)` →
   `FirecrackerWorkerPool.submit(request)`.
5. Pool acquires an idle VM, sends `("request", request_id, (request, config))`
   frame over vsock.
6. Guest worker deserializes the frame, calls `_pool_worker_body`, streams
   chunks back as `("chunk", request_id, payload)` frames.
7. Host bridge reads frames, pushes to `asyncio.Queue`, `submit` yields chunks.
8. Terminal frame (`done`/`error`/`cancelled`/`timeout`) ends the stream.

## Error Handling

- **Missing binary/images**: `FileNotFoundError` at factory construction (fail fast).
- **Guest connect timeout**: VM shutdown + `RuntimeError` at pool spawn.
- **Cooperative cancel**: `cancel_request()` sends a `"cancel"` frame; guest
  worker detects it and emits a `"cancelled"` terminal.
- **Force kill**: `force_kill_worker_by_loop_id()` sends `CtrlAltDel` via the
  firecracker API, then escalates to SIGTERM/SIGKILL. Respawns a warm VM to
  maintain min pool size.
- **Client disconnect**: `_schedule_abandon_drain()` drains remaining frames
  until a terminal, then releases the worker.

## File Manifest

| File | Change |
|------|--------|
| `packages/soothe-daemon/src/soothe_daemon/config/models.py` | Added `FirecrackerConfig` |
| `packages/soothe-daemon/src/soothe_daemon/config/settings.py` | Wired `firecracker` field + `validate_runner_mode` |
| `packages/soothe-daemon/src/soothe_daemon/config/__init__.py` | Exported `FirecrackerConfig` |
| `packages/soothe-daemon/src/soothe_daemon/runner/firecracker_runner.py` | New: `_VsockStreamBridge`, `FirecrackerWorker`, `FirecrackerWorkerPool`, `FirecrackerLoopRunner` |
| `packages/soothe-daemon/src/soothe_daemon/runner/factory.py` | Wired `firecracker` mode into `__init__`, `get_shared_execution_pool`, `initialize_pool`, `shutdown_pool`, `create_runner` |
| `packages/soothe-daemon/tests/unit/runner/test_firecracker_runner.py` | New: factory mode selection, fail-fast, config validation, identity incompatibility |
| `CHANGELOG.md` | `### Added` entry under `[Unreleased]` |

## Testing

All tests are mock-based — no real microVMs or vsock required.

- `TestLoopRunnerFactoryFirecrackerMode`: factory returns
  `FirecrackerLoopRunner` when `firecracker.enabled=True`; fails fast when
  binary/kernel/rootfs missing; no firecracker imports leak into other modes.
- `TestFirecrackerConfigValidation`: `validate_runner_mode` accepts
  `firecracker` alone; rejects `firecracker` + any other mode.
- `TestFirecrackerIdentityValidation`: identity + firecracker rejected.
- `TestFirecrackerConfigDefaults`: default config has firecracker disabled
  with sensible VM defaults.

## Backward Compatibility

- `firecracker.enabled` defaults to `False`; default config still selects
  `thread_pool`. No behavioral change to existing runners.
- No DAG boundary change: all new code in `soothe-daemon`.
- The `firecracker_runner` module is import-safe on non-Linux (no
  import-time crash), but `LoopRunnerFactory` raises `RuntimeError` if
  `runner_mode='firecracker'` is selected on a non-Linux host.
  **Firecracker is officially supported on Linux only** — `AF_VSOCK`,
  the `firecracker` binary, and KVM require a Linux host.

## Out of Scope

- **Rootfs image build**: the rootfs (with the Soothe worker Python env +
  entrypoint) is built by a separate image-build script; the config points at
  pre-built kernel/rootfs paths.
- **Guest-side vsock worker entrypoint**: the guest rootfs contains a
  `soothe-firecracker-worker` entrypoint script that sets up vsock and calls
  `_pool_worker_body`. This script is part of the image-build tooling.
- **virtio-fs mount configuration**: the `workspace_mount_mode` config selects
  between `"virtiofs"` (local single-host) and `"sync"` (workspace_sync S3
  backend for remote pools). The virtio-fs device configuration is part of the
  VM boot configuration, driven by the rootfs entrypoint.
