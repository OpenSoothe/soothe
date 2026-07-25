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
soothed setup                 # scaffold nano.yml / soothe.yml / daemon.yml + provider wizard
soothed start --foreground
soothed status
soothed doctor
soothed stop
```

## Configuration

- `~/.soothe/config/nano.yml` — Agent config (`SootheConfig`)
- `~/.soothe/config/soothe.yml` — Host overlay (StrangeLoop / autopilot / cron)
- `~/.soothe/config/daemon.yml` — Daemon config (`SootheDaemonConfig`)

Run `soothed setup` (or `soothed setup --yes`) to create these from packaged templates.

## Dependencies

- `soothe>=0.9.4` — In-process agent core (pulls soothe-nano)
- `soothe-sdk>=1.0.5` — wire/events/display contracts

Do **not** depend on `soothe-client-python` at runtime; use `soothe_sdk.wire`
(or `soothe_daemon.admin_rpc` for `soothed` admin commands). Tests may install
the client via the `dev` extra.
