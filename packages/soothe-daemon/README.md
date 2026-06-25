# soothe-daemon

Soothe daemon server — long-running agent runtime with WebSocket/HTTP transports.

## Installation

```bash
pip install soothe-daemon
```

For full runtime, also install the agent core and CLI:

```bash
pip install soothe soothe-daemon soothe-cli
```

## Usage

```bash
soothed start --foreground
soothed status
soothed doctor
soothed stop
```

## Configuration

- `~/.soothe/config/config.yml` — Agent config (`SootheConfig`)
- `~/.soothe/config/daemon.yml` — Daemon config (`SootheDaemonConfig`)

## Dependencies

- `soothe>=0.5.0` — In-process agent core
- `soothe-sdk>=0.5.10` — WebSocket protocol