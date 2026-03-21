- Support Dual protocols, domain socket and WebSocket
- Optimize SootheRunner starting speed


Design: Extendable Front-Back Ends for Soothe Server

Goals

- Create a unified backend (daemon server) to serve multiple frontends:
- CLI
- TUI
- Web
- Desktop Apps

Backend Protocol Support

- DomainSocket - for CLI and TUI frontends
- WebSocket - for Web and Desktop App frontends

Architecture Principles

- Maintain current event-based design for progress synchronization between frontends and backend

Documentation Tasks

- Create a new RFC specification for this architecture
- Update existing RFCs to align with the new design

Request

- Propose design alternatives if there are better solutions available