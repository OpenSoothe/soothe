---
title: Language Clients
parent: Wiki
nav_order: 3
description: >-
  Official WebSocket clients for soothe-daemon — Python, TypeScript, Go, and Rust.
permalink: /wiki/clients/
---

# Language Clients

Talk to a running **soothe-daemon** over protocol-1 WebSocket. Same wire contract across languages.

| Language | Package | Install | Latest |
|----------|---------|---------|--------|
| Python | [`soothe-client-python`](https://pypi.org/project/soothe-client-python/) | `pip install soothe-client-python` | [![PyPI](https://img.shields.io/pypi/v/soothe-client-python.svg)](https://pypi.org/project/soothe-client-python/) |
| TypeScript | [`@mirasoth/soothe-client`](https://www.npmjs.com/package/@mirasoth/soothe-client) | `npm i @mirasoth/soothe-client` | [![npm](https://img.shields.io/npm/v/@mirasoth/soothe-client.svg)](https://www.npmjs.com/package/@mirasoth/soothe-client) |
| Go | [`soothe-client-go`](https://github.com/mirasoth/soothe-client-go) | `go get github.com/mirasoth/soothe-client-go@latest` | [![Go](https://img.shields.io/github/v/release/mirasoth/soothe-client-go?label=go)](https://github.com/mirasoth/soothe-client-go/releases) |
| Rust | [`soothe-client`](https://crates.io/crates/soothe-client) | `cargo add soothe-client` | [![crates.io](https://img.shields.io/crates/v/soothe-client.svg)](https://crates.io/crates/soothe-client) |

Default endpoint: `ws://127.0.0.1:8765`.

## API tiers

| Need | Entry point |
|------|-------------|
| One conversation, stream replies | `DaemonSession` / appkit |
| Jobs / cron / autopilot one-shots | `CommandClient` / `AsyncCommandClient` |
| Raw protocol / custom RPCs | `Client` |
| Multi-user HTTP backend | `ConnectionPool` + `TurnRunner` |

Route specialists with `preferred_subagent` (`deep_research`, `academic_research`, `browser_use`, `planner`).

## Repositories

- [soothe-client-python](https://github.com/mirasoth/soothe-client-python)
- [soothe-client-typescript](https://github.com/mirasoth/soothe-client-typescript)
- [soothe-client-go](https://github.com/mirasoth/soothe-client-go)
- [soothe-client-rust](https://github.com/mirasoth/soothe-client-rust)

Monorepo checkouts live under [`client/`](../../client/). Wire contract: [AsyncAPI](../specs/asyncapi.yaml) / [Daemon API](api-reference/daemon-api.md).

## Related

- [Quick Start](getting-started/Quick-Start.md) — install CLI + daemon
- [Daemon API](api-reference/daemon-api.md) — server surface
- [SDK API](api-reference/sdk-api.md) — plugins & shared contracts (not transport)
