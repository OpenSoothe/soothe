# soothe-daemon

Soothe daemon server — long-running agent runtime with WebSocket and HTTP transports.

This package hosts the multi-transport daemon that wraps the in-proc agent
core (`soothe`) and serves clients (`soothe-cli`, custom clients via
`soothe-sdk`) over WebSocket and optional HTTP REST.

## Installation

```bash
pip install soothe-daemon
```

The package ships the `soothed` console script for daemon lifecycle:

```bash
soothed start --foreground
soothed status
soothed doctor
soothed stop
```

## Configuration

The daemon reads two YAML files, both under `~/.soothe/config/`:

- `config.yml` — `SootheConfig`: providers, agent_loop, persistence, etc.
- `daemon_config.yml` — `SootheDaemonConfig`: transports (WebSocket/HTTP),
  worker pool, distributed (Ray) settings, queue/dispatch limits.

`SootheDaemonConfig.soothe_config_path` points at the `SootheConfig` YAML the
daemon will load for the agent it hosts.

## Architecture

```
soothe-daemon  <-- this package
   ├── server, transports, message_router, query_engine
   ├── runner (LoopRunnerFactory: pool / Ray / local subprocess)
   ├── health checks (soothed doctor)
   └── cli (soothed)
        |
        v
soothe         <-- in-proc agent core (SootheRunner, SootheConfig, ...)
soothe-sdk     <-- WebSocket protocol + client
```
