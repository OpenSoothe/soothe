# Implementation Guide: BoxLite Container Runner Sandbox

**Guide**: IG-773
**Title**: BoxLite Container Runner Sandbox
**Created**: 2026-09-02
**Related RFCs**: RFC-221 (Loop Runner Protocol), RFC-906 (Workspace Sync Architecture)

## Abstract

This guide documents the addition of a fifth `LoopRunnerProtocol` implementation —
`BoxLiteLoopRunner` — that executes Soothe agent loops inside lightweight Docker
containers. It joins the existing thread (`ThreadLoopRunner`), process
(`ProcessLoopRunner`), Ray (`RayLoopRunner`), and Firecracker
(`FirecrackerLoopRunner`) runners, selectable via daemon config
(`loop_runner.runner_mode='boxlite'`).

## Motivation

The existing `firecracker` mode provides strong VM-level isolation but is
**Linux-only** — it requires `AF_VSOCK`, KVM, and a Linux host. Developers and
operators on macOS or Windows cannot use Firecracker isolation. BoxLite fills
this gap: it provides **container-level isolation** using Docker, which is
available on all major platforms (Linux, macOS via Docker Desktop, Windows via
Docker Desktop/WSL2).

BoxLite is the cross-platform isolation substrate:
- **Firecracker**: strongest isolation (hardware VM), Linux-only
- **BoxLite**: strong isolation (container), cross-platform
- **ProcessPool**: moderate isolation (subprocess), cross-platform
- **ThreadPool**: no isolation (shared memory), cross-platform

## Architecture

```
LoopRunnerFactory  (mode: thread_pool | process_pool | ray | firecracker | boxlite)
    │
    ├── boxlite mode
    │       └── BoxLiteLoopRunner  (per loop_id, delegates to shared BoxLiteWorkerPool)
    │               └── BoxLiteWorkerPool  (warm pool of N containers)
    │                       ├── per-container: docker run + TCP port + guest worker
    │                       │     └── _pool_worker_body (reuse) → SootheRunner.astream()
    │                       │           │ chunks via TCP stream
    │                       │           ▼
    │                       │     _TcpStreamBridge (host side) → asyncio.Queue
    │                       └── submit(request) → async generator
    │
    └── (existing) thread_pool / process_pool / ray / firecracker — unchanged
```

No DAG boundary change: all new code lives in `soothe-daemon` (runner + config),
reusing `soothe.protocols.runner.LoopRunnerProtocol` (already in `soothe`).

## Components

### BoxLiteConfig (`config/models.py`)

Configuration model with 14 fields:
- `container_image`: Docker image containing the Soothe worker env + entrypoint.
- `docker_binary_path`: Path to the `docker` CLI binary (default `"docker"`).
- `min_pool_size` / `max_pool_size`: Pool sizing (default 1 / 4).
- `tcp_port_base`: Base TCP port for host↔container IPC (default 50000).
- `container_cpu_count`: CPU limit per container (Docker `--cpus`, default 2.0).
- `container_mem_limit`: Memory limit per container (default `"2g"`).
- `idle_timeout_seconds`: Idle container timeout (default 300s).
- `max_requests_per_worker`: Max requests before container respawn (default 100).
- `request_timeout_seconds`: Default per-request timeout (default 0 = no timeout).
- `reuse_runner` / `warmup_runner` / `warmup_core_agent`: Runner warmup flags.
- `workspace_mount_mode`: `"bind"` (local bind mount) or `"sync"` (workspace_sync S3).
- `extra_container_args`: Extra arguments appended to the `docker run` command.

### _TcpStreamBridge (`boxlite_runner.py`)

Host-side TCP reader that:
1. Binds a listener on `127.0.0.1:{tcp_port_base + worker_index}`.
2. Accepts the container's inbound TCP connection.
3. Reads length-prefixed pickled frames (4-byte big-endian length + payload).
4. Pushes 3-tuple frames `(msg_type, request_id, payload)` into an `asyncio.Queue`.
5. Supports cooperative cancel via `"cancel"` frame; force-kill via socket close.

Uses standard `socket.AF_INET` / `SOCK_STREAM` — no platform-specific APIs.

### BoxLiteWorkerPool (`boxlite_runner.py`)

Singleton pool mirroring `ProcessPool`'s shape:
- `get_shared_instance()` / `close_shared_instance()`: singleton lifecycle.
- `_spawn_warm_container()`: starts a Docker container with `docker run --rm`,
  CPU/memory limits, env vars (`SOOTHE_WORKER_ID`, `SOOTHE_TCP_PORT`,
  `SOOTHE_TCP_HOST=host.docker.internal`), and optional workspace bind mount.
- `submit(request)`: acquires an idle container, sends the pickled
  `LoopRunRequest` + `spawn_safe_config` over TCP, yields stream chunks.
- `cancel_request(loop_id)`: sends a cooperative cancel frame.
- `force_kill_worker_by_loop_id(loop_id)`: runs `docker stop`, then SIGTERM/SIGKILL.
- `_health_loop()`: reaps idle containers, maintains min pool size.

### BoxLiteLoopRunner (`boxlite_runner.py`)

Thin per-`loop_id` facade implementing `LoopRunnerProtocol`:
- `run()` → delegates to `BoxLiteWorkerPool.submit()`.
- `cancel()` → delegates to `pool.cancel_request()`.
- `is_idle()` → `not pool.is_loop_busy()`.
- `force_kill()` → `pool.force_kill_worker_by_loop_id()`.
- `set_clarification_mode()` → returns `False` (container isolation).

## Data Flow

1. `LoopRunnerFactory.__init__` validates `docker` binary presence and
   `container_image` is set (fail fast, like the Firecracker binary check).
2. `initialize_pool()` pre-warms `min_pool_size` containers.
3. Each container's entrypoint connects back to the host's TCP listener.
4. `submit(request)` sends `(request, spawn_safe_config)` as a pickled frame.
5. The container's `_pool_worker_body` processes the request and streams
   `(msg_type, request_id, payload)` frames back.
6. The host yields `payload` for `"chunk"` frames; breaks on terminal types
   (`"done"`, `"error"`, `"timeout"`, `"cancelled"`).

## Error Handling

- **Docker not installed**: `FileNotFoundError` at factory construction time.
- **Container image not set**: `ValueError` at factory construction time.
- **Container connect timeout**: `RuntimeError` after 60s grace period.
- **Container crash**: `is_alive` returns `False`; health loop reaps and respawns.
- **Cancel**: cooperative TCP frame → `docker stop` → SIGTERM → SIGKILL ladder.
- **Identity service**: rejected at factory construction (same as process/firecracker).

## File Manifest

| File | Change |
|------|--------|
| `config/models.py` | New `BoxLiteConfig` model; `boxlite` field in `LoopRunnerConfig`; `runner_mode` Literal extended |
| `config/__init__.py` | Export `BoxLiteConfig` |
| `runner/boxlite_runner.py` | **New module**: `_TcpStreamBridge`, `BoxLiteWorker`, `BoxLiteWorkerPool`, `BoxLiteLoopRunner` |
| `runner/factory.py` | `boxlite` branch in `__init__`, `get_shared_execution_pool`, `initialize_pool`, `shutdown_pool`, `create_runner`; identity guard extended |
| `tests/unit/runner/test_boxlite_runner.py` | **New test file**: 13 tests |
| `docs/impl/IG-773-boxlite-runner-sandbox.md` | This design doc |
| `CHANGELOG.md` | `### Added` entry |

## Testing

All tests are mock-based — no real Docker containers required:
- Factory mode selection: `create_runner` returns `BoxLiteLoopRunner` when `boxlite` mode.
- Fail-fast validation: `FileNotFoundError` when Docker binary missing; `ValueError` when image not set.
- Config validation: `boxlite` valid when selected; invalid when `thread_pool` selected.
- Identity incompatibility: rejected with `ValueError`.
- Default config: `runner_mode='thread_pool'` by default; `BoxLiteConfig` defaults verified.
- Cross-platform: no platform guard (works on both `darwin` and `linux`).
- Import isolation: `boxlite_runner` not imported in thread/process/ray/firecracker modes.

## Backward Compatibility

- `runner_mode` Literal extended from 4 to 5 values — existing values unchanged.
- `boxlite.enabled` defaults to `False` (via `runner_mode='thread_pool'` default).
- No change to existing runner behavior.
- New `boxlite` sub-config is additive — absent from YAML → defaults apply.

## Out of Scope

- **Container image build**: the Docker image (with the Soothe worker Python env +
  entrypoint) is built by a separate image-build script (not part of this change);
  the config points at a pre-built image.
- **Docker Compose orchestration**: for multi-container coordination, use the
  existing Ray distributed mode.
- **Kubernetes deployment**: BoxLite targets single-host Docker; K8s deployments
  should use the Ray runner with KubeRay.
